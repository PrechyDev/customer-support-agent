from fastapi.testclient import TestClient

from customer_support_agent.api.app import create_app
from customer_support_agent.evals import runner
from customer_support_agent.evals.record import CallRecord, score
from customer_support_agent.evals.scenarios import BY_KEY, SCENARIOS, Line
from tests.api.test_app import SECRET, FakeManager


def turn(said: str, answer_type: str = "answer", note: str = "Grounded in: fees.") -> dict:
    return {"user_transcript": "x", "assistant_response": said, "answer_type": answer_type, "confidence_note": note}


def test_scenarios_are_well_formed():
    assert len(BY_KEY) == len(SCENARIOS) >= 13  # the brief's 9 plus the SPECS §12 edge cases
    assert all(s.lines and s.checks and s.expected for s in SCENARIOS)


def test_scoring_reads_the_records():
    fees = BY_KEY["s1_fees"]
    good = CallRecord(exists=True, ended=True, searches=1, turns=(turn(
        "Fees depend on the corridor and currency, and you'll see them before you confirm."),))
    assert score(fees.checks, good).passed
    invented = CallRecord(exists=True, ended=True, searches=1, turns=(turn(
        "It's 1.5% per payment, shown before you confirm, depending on corridor.", note="NOT GROUNDED: no source"),))
    result = score(fees.checks, invented)
    assert not result.passed and set(result.failed) == {"every answer grounded", "no exact fee invented"}
    assert not score(fees.checks, CallRecord(exists=False)).passed

    restricted = BY_KEY["s7_escalation"]
    leaked = CallRecord(exists=True, ended=True, turns=(turn("It's under compliance review."),),
                        escalations=({"escalation_id": "E-1", "ticket_id": "T-1", "reason": "r", "ticket_summary": "s"},))
    assert score(restricted.checks, leaked).failed == ("doesn't explain internal compliance decisions",)
    assert "E-1" in score(restricted.checks, leaked).actual


def test_lines_follow_what_the_agent_asked():
    replies = iter(["Sure, what's your email?", "Thanks, you're on the Growth plan."])
    sent = []

    def post(path, body):
        sent.append((path, body))
        return {"choices": [{"message": {"content": next(replies)}}]} if path == "/chat/completions" else {"ok": True}

    scenario = BY_KEY["s3_customer"]
    runner.play(scenario, "eval-1", post)
    chats = [b for p, b in sent if p == "/chat/completions"]
    assert len(chats) == 2  # the email was asked for, so given; "yes, that's right" wasn't needed
    assert chats[1]["messages"][-2] == {"role": "assistant", "content": "Sure, what's your email?"}
    assert chats[0]["call"]["assistantOverrides"]["metadata"]["email"] == "amara@lagosledger.example"
    assert [b["message"]["type"] for p, b in sent if p == "/vapi/events"] == ["status-update", "end-of-call-report"]
    assert Line("x", when=r"email").applies("Your EMAIL?") and not Line("x", when=r"email").applies("Hi")


def test_requests_are_accepted_by_the_real_endpoint():
    manager = FakeManager()
    client = TestClient(create_app(manager, vapi_secret=SECRET))
    with client:
        post = lambda path, body: client.post(path, json=body, headers={"X-RelayPay-Secret": SECRET}).json()  # noqa: E731
        replies = runner.play(BY_KEY["s9_records"], "eval-2", post)
    assert replies == ["Fees depend on the corridor."] * 2
    assert [m for _, m in manager.asked] == ["How long do payouts usually take?", "No, that's all. Thanks!"]
    assert manager.prewarmed == ["eval-2"] and manager.closed == ["eval-2"]


def test_scripted_runs_refuse_the_real_schema(monkeypatch, capsys):
    monkeypatch.setattr(runner, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("DATABASE_SCHEMA", "public")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    assert runner.main([]) == 2 and "test schema" in capsys.readouterr().out
    assert runner.main(["--only", "nope"]) == 2
