"""The voice page's endpoints (FRONTEND_PLAN §5.1, §8)."""

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from customer_support_agent.api.web import mount_web, voice_router
from customer_support_agent.config import VoiceSettings
from tests.mcp_server.fake_repo import FakeRepository

VOICE = VoiceSettings(public_key="pk_public", assistant_id="asst-1")


def client(repo=None, voice=VOICE, now=None):
    app = FastAPI()
    if now:
        app.include_router(voice_router(voice, repo, now=now))
    else:
        mount_web(app, voice, repo)
    return TestClient(app)


def call_with(repo, cid="call-1", escalation=None, ticket=False):
    repo.ensure_conversation(cid)
    if ticket:
        repo.create_ticket(cid, None, "payment", "medium", "Failed invoice payment", "TXN-9004")
    if escalation:
        repo.escalation_rows.append({"escalation_id": "E-1033", "conversation_id": cid, "category": "account",
                                     "user_email": "precious@gmail.com", **escalation})
    return cid


def test_page_and_static_files_are_served():
    c = client()
    page = c.get("/")
    assert page.status_code == 200 and "Customer support" in page.text
    assert page.headers["x-frame-options"] == "DENY"
    assert c.get("/static/shared/tokens.css").status_code == 200


def test_voice_config_returns_only_the_two_public_values():
    assert client().get("/voice/config").json() == {"publicKey": "pk_public", "assistantId": "asst-1"}
    missing = client(voice=VoiceSettings(public_key="pk_public", assistant_id=None)).get("/voice/config")
    assert missing.status_code == 503 and missing.json() == {"error": "voice_unavailable"}


def test_outcome_matches_the_record():
    repo = FakeRepository()
    callback = {"contact_method": "call", "call_booked": True, "callback_timezone": "Africa/Lagos",
                "callback_start_utc": datetime(2026, 10, 2, 9, tzinfo=UTC),
                "callback_end_utc": datetime(2026, 10, 2, 11, tzinfo=UTC)}
    call_with(repo, "cb", callback)
    call_with(repo, "any", {"contact_method": "call", "call_booked": False})
    call_with(repo, "mail", {"contact_method": "email", "call_booked": False})
    call_with(repo, "tkt", ticket=True)
    call_with(repo, "none")
    c = client(repo)
    get = lambda cid: c.get(f"/voice/calls/{cid}/outcome").json()

    assert get("cb") == {"outcome": "callback", "reference": "E-1033", "email_masked": None,
                         "callback": "Friday 2 October, between 10am and 12pm Lagos time"}
    assert get("any")["outcome"] == "callback" and get("any")["callback"] is None
    assert get("mail")["outcome"] == "email" and get("mail")["email_masked"] == "p***@gmail.com"
    assert get("tkt")["outcome"] == "ticket" and get("tkt")["reference"].startswith("T-")
    assert get("none") == {"outcome": "none", "reference": None, "callback": None, "email_masked": None}
    assert "precious" not in c.get("/voice/calls/mail/outcome").text  # never the full email


def test_outcome_is_only_for_a_recent_known_call():
    repo = FakeRepository()
    call_with(repo, "call-1")
    later = client(repo, now=lambda: datetime.now(UTC) + timedelta(hours=3))
    assert later.get("/voice/calls/call-1/outcome").status_code == 404  # older than 2 hours
    c = client(repo)
    assert c.get("/voice/calls/unknown/outcome").status_code == 404
    assert c.get("/voice/calls/bad%20id!/outcome").status_code == 404
    assert client(FakeRepository(down=True)).get("/voice/calls/call-1/outcome").status_code == 503
    assert client(None).get("/voice/calls/call-1/outcome").status_code == 503  # no database configured


def test_rating_is_saved_once():
    repo = FakeRepository()
    call_with(repo, "call-1")
    c = client(repo)
    assert c.post("/voice/calls/call-1/rating", json={"helpful": False}).json() == {"ok": True}
    assert c.post("/voice/calls/call-1/rating", json={"helpful": True}).json() == {"ok": True}
    assert repo.conversations["call-1"]["rating"] == "no"  # the later one is ignored
    assert c.post("/voice/calls/call-1/rating", json={"helpful": "yes"}).status_code == 422
    later = client(repo, now=lambda: datetime.now(UTC) + timedelta(hours=3))
    assert later.post("/voice/calls/call-1/rating", json={"helpful": True}).status_code == 404
