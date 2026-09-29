import json

from fastapi.testclient import TestClient

from customer_support_agent.api.app import create_app
from customer_support_agent.api.auth import check_vapi_secret
from customer_support_agent.agent.session import TextDelta, TurnResult

SECRET = "v" * 32
BODY = {"stream": True, "call": {"id": "call-1"}, "messages": [{"role": "user", "content": "what fees?"}]}


class FakeManager:
    def __init__(self):
        self.asked = []
        self.closed_all = False

    async def ask(self, call_id, message):
        self.asked.append((call_id, message))
        yield TextDelta("Fees depend ")
        yield TextDelta("on the corridor.")
        yield TurnResult(outcome="ok", text="Fees depend on the corridor.")

    async def close_idle(self):
        return []

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


def test_secret_check_accepts_bearer_or_raw_value():
    assert check_vapi_secret(f"Bearer {SECRET}", SECRET) == "bearer"
    assert check_vapi_secret(SECRET, SECRET) == "raw"
    assert check_vapi_secret("Bearer nope", SECRET) is None
    assert check_vapi_secret(None, SECRET) is None
