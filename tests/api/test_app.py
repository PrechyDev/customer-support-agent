import asyncio
import json

from fastapi.testclient import TestClient

from customer_support_agent.agent import fallbacks
from customer_support_agent.api.app import create_app
from customer_support_agent.api.auth import check_vapi_secret, describe_auth_header
from customer_support_agent.agent.session import TextDelta, TurnResult

SECRET = "v" * 32
BODY = {"stream": True, "call": {"id": "call-1"}, "messages": [{"role": "user", "content": "what fees?"}]}


class FakeManager:
    def __init__(self):
        self.asked = []
        self.closed_all = False
        self.prewarmed = []
        self.closed = []

    async def ask(self, call_id, message):
        self.asked.append((call_id, message))
        yield TextDelta("Fees depend ")
        yield TextDelta("on the corridor.")
        yield TurnResult(outcome="ok", text="Fees depend on the corridor.")

    async def close_idle(self):
        return []

    async def prewarm(self, call_id):
        self.prewarmed.append(call_id)

    async def close(self, call_id):
        self.closed.append(call_id)

    async def run_idle_reaper(self, interval_seconds=30):
        return None

    async def close_all(self):
        self.closed_all = True


def client(manager):
    return TestClient(create_app(manager, vapi_secret=SECRET))


def contents(sse_text):
    events = [line[len("data: "):] for line in sse_text.splitlines() if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    return "".join(json.loads(e)["choices"][0]["delta"].get("content") or "" for e in events[:-1])


def test_streams_the_agent_reply_as_sse():
    manager = FakeManager()
    with client(manager) as c:
        response = c.post("/chat/completions", json=BODY, headers={"Authorization": f"Bearer {SECRET}"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert contents(response.text) == "Fees depend on the corridor."
    assert manager.asked == [("call-1", "what fees?")]
    assert manager.closed_all  # sessions closed on shutdown


def test_only_a_slow_reply_hears_the_reassurance():
    class SlowManager(FakeManager):
        async def ask(self, call_id, message):
            await asyncio.sleep(0.3)  # e.g. a slow tool call
            async for event in super().ask(call_id, message):
                yield event

    auth = {"Authorization": f"Bearer {SECRET}"}
    with TestClient(create_app(SlowManager(), vapi_secret=SECRET, reassure_after=0.1)) as c:
        slow = contents(c.post("/chat/completions", json=BODY, headers=auth).text)
    with TestClient(create_app(FakeManager(), vapi_secret=SECRET, reassure_after=1.0)) as c:
        fast = contents(c.post("/chat/completions", json=BODY, headers=auth).text)
    assert slow == f"{fallbacks.REASSURANCE} Fees depend on the corridor."
    assert fast == "Fees depend on the corridor."  # no filler on normal turns


def test_vapi_events_prewarm_on_call_start_and_close_on_call_end():
    manager = FakeManager()
    auth = {"X-RelayPay-Secret": SECRET}
    started = {"message": {"type": "status-update", "status": "in-progress", "call": {"id": "call-9"}}}
    ended = {"message": {"type": "end-of-call-report", "call": {"id": "call-9"}}}
    with client(manager) as c:
        assert c.post("/vapi/events", json=started).status_code == 401  # no secret
        assert c.post("/vapi/events", json={"nope": 1}, headers=auth).status_code == 400
        assert c.post("/vapi/events", json=started, headers=auth).json() == {"ok": True}
        assert c.post("/vapi/events", json=ended, headers=auth).json() == {"ok": True}
    assert manager.prewarmed == ["call-9"] and manager.closed == ["call-9"]


def test_non_streaming_request_gets_one_json_reply():
    with client(FakeManager()) as c:
        response = c.post("/chat/completions", json={**BODY, "stream": False}, headers={"Authorization": SECRET})
    assert response.json()["choices"][0]["message"] == {"role": "assistant", "content": "Fees depend on the corridor."}


def test_rejects_bad_secret_and_bad_body_and_serves_health():
    manager = FakeManager()
    with client(manager) as c:
        assert c.post("/chat/completions", json=BODY).status_code == 401
        assert c.post("/chat/completions", json=BODY, headers={"Authorization": "Bearer wrong"}).status_code == 401
        bad = c.post("/chat/completions", json={"messages": []}, headers={"Authorization": f"Bearer {SECRET}"})
        assert bad.status_code == 400
        assert c.get("/health").json() == {"status": "ok"}
    assert manager.asked == []


def test_secret_in_custom_header_is_accepted_even_with_a_foreign_authorization():
    """Shared Vapi org: Authorization carries the org's key, our secret comes in X-RelayPay-Secret."""
    manager = FakeManager()
    with client(manager) as c:
        headers = {"Authorization": "Bearer someone-elses-org-key", "X-RelayPay-Secret": SECRET}
        assert c.post("/chat/completions", json=BODY, headers=headers).status_code == 200
        wrong = {"Authorization": "Bearer someone-elses-org-key", "X-RelayPay-Secret": "nope"}
        assert c.post("/chat/completions", json=BODY, headers=wrong).status_code == 401
    assert len(manager.asked) == 1


def test_secret_check_accepts_bearer_or_raw_value():
    assert check_vapi_secret(f"Bearer {SECRET}", SECRET) == "bearer"
    assert check_vapi_secret(SECRET, SECRET) == "raw"
    assert check_vapi_secret("Bearer nope", SECRET) is None
    assert check_vapi_secret(None, SECRET) is None
    # rejection logs describe the header without its value
    assert describe_auth_header(None) == "missing"
    assert describe_auth_header("Bearer abc") == "Bearer, 3 chars"
    assert describe_auth_header("abcd") == "no Bearer prefix, 4 chars"
