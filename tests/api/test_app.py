import asyncio
import json

from fastapi.testclient import TestClient

from customer_support_agent.agent import fallbacks
from customer_support_agent.api.app import create_app
from customer_support_agent.api.auth import check_vapi_secret, describe_auth_header
from customer_support_agent.agent.session import TextDelta, TurnResult
from customer_support_agent.api.records import CallRecorder
from tests.mcp_server.fake_repo import FakeRepository

SECRET = "v" * 32
BODY = {"stream": True, "call": {"id": "call-1"}, "messages": [{"role": "user", "content": "what fees?"}]}


class FakeManager:
    def __init__(self):
        self.asked = []
        self.closed_all = False
        self.prewarmed = []
        self.closed = []
        self.callers = []

    async def ask(self, call_id, message, caller=None):
        self.asked.append((call_id, message))
        self.callers.append(caller)
        yield TextDelta("Fees depend ")
        yield TextDelta("on the corridor.")
        yield TurnResult(outcome="ok", text="Fees depend on the corridor.", answer_type="answer",
                         sources=("fees",), kb_chunks=("fees",), tools_used=("mcp__relaypay__search_knowledge_base",))

    async def close_idle(self):
        return []

    async def prewarm(self, call_id, caller=None):
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
        async def ask(self, call_id, message, caller=None):
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


def test_agent_is_told_what_the_caller_heard_when_cut_off():
    manager = FakeManager()
    auth = {"Authorization": f"Bearer {SECRET}"}

    def turn(previous_reply_as_heard):
        messages = [{"role": "user", "content": "what fees?"}]
        if previous_reply_as_heard is not None:
            messages += [{"role": "assistant", "content": previous_reply_as_heard}, {"role": "user", "content": "go on"}]
        c.post("/chat/completions", json={**BODY, "messages": messages}, headers=auth)

    with client(manager) as c:
        turn(None)  # we send "Fees depend on the corridor."
        turn("Fees depend●")  # the caller cut in after two words
        turn("Fees depend on the corridor.")  # this time they heard it all
    first, cut_off, complete = (message for _, message in manager.asked)
    assert first == "what fees?"
    assert cut_off == '[System note: your last reply was cut off. The customer only heard: "Fees depend"]\ngo on'
    assert complete == "go on"


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


def test_call_is_recorded_with_the_form_each_turn_its_grounding_and_vapis_summary():
    repo = FakeRepository()
    manager = FakeManager()
    form = {"name": "Ada <Obi>", "email": "ada at example dot com", "company": "Obi Ltd"}
    started = {"message": {"type": "status-update", "status": "in-progress",
                           "call": {"id": "call-1", "assistantOverrides": {"metadata": form}}}}
    ended = {"message": {"type": "end-of-call-report", "call": {"id": "call-1"}, "analysis": {"summary": "Asked about fees."}}}
    auth = {"X-RelayPay-Secret": SECRET}
    with TestClient(create_app(manager, vapi_secret=SECRET, recorder=CallRecorder(repo, model="m"))) as c:
        c.post("/vapi/events", json=started, headers=auth)
        c.post("/chat/completions", json=BODY, headers=auth)
        c.post("/vapi/events", json=ended, headers=auth)
    clean = {"name": "Ada Obi", "email": "ada@example.com", "company": "Obi Ltd"}  # tags stripped, email normalised
    assert manager.callers == [clean]
    conv = repo.conversations["call-1"]
    assert (conv["caller_name"], conv["caller_email"], conv["model"]) == ("Ada Obi", "ada@example.com", "m")
    (cid, heard, said, answer_type, note, first_ms, total_ms), = repo.turns
    assert (heard, said, answer_type, note) == ("what fees?", "Fees depend on the corridor.", "answer", "Grounded in: fees.")
    assert repo.closed == [("call-1", "Asked about fees.")]


def test_a_down_database_never_breaks_the_call():
    with TestClient(create_app(FakeManager(), vapi_secret=SECRET, recorder=CallRecorder(FakeRepository(down=True)))) as c:
        response = c.post("/chat/completions", json=BODY, headers={"X-RelayPay-Secret": SECRET})
    assert contents(response.text) == "Fees depend on the corridor."


def test_an_overlong_message_never_reaches_claude():
    manager = FakeManager()
    body = {**BODY, "messages": [{"role": "user", "content": "word " * 500}]}  # 2,500 characters
    with client(manager) as c:
        response = c.post("/chat/completions", json=body, headers={"X-RelayPay-Secret": SECRET})
    assert contents(response.text) == fallbacks.TOO_LONG
    assert manager.asked == []


def test_a_request_vapi_cancelled_before_anything_was_said_is_not_a_turn():
    class Cancelled(FakeManager):
        async def ask(self, call_id, message, caller=None):
            self.asked.append((call_id, message))
            return
            yield  # an agent turn that ended with nothing said and no result (Vapi cancelled it)

    repo = FakeRepository()
    with TestClient(create_app(Cancelled(), vapi_secret=SECRET, recorder=CallRecorder(repo))) as c:
        c.post("/chat/completions", json=BODY, headers={"X-RelayPay-Secret": SECRET})
    assert repo.turns == []
