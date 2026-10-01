"""The console API end to end against the real database, in the throwaway `test` schema.

Run with: RUN_DB_TESTS=1 poetry run pytest tests/api/test_console_integration.py
Everything it creates (team members, a call, its case and timeline) is deleted afterwards.
"""

import os
import secrets
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from customer_support_agent.api.app import create_app
from customer_support_agent.config import ConsoleSettings
from customer_support_agent.console import security, views
from customer_support_agent.db.console_store import ConsoleStore
from customer_support_agent.db.repository import Repository
from customer_support_agent.mcp_server.tools import cases
from tests.api.test_app import FakeManager

pytestmark = pytest.mark.skipif(os.environ.get("RUN_DB_TESTS") != "1",
                                reason="database tests run only with RUN_DB_TESTS=1")

SECRET = "v" * 32
CSRF = {"X-Requested-With": "relaypay-console"}
PASSWORD = "a-long-passphrase"


@pytest.fixture(scope="module")
def env():
    from dotenv import find_dotenv, load_dotenv

    from customer_support_agent.config import load_database_url

    load_dotenv(find_dotenv(usecwd=True))
    repo = Repository(load_database_url(), schema="test")
    repo.open()
    store = ConsoleStore(repo)
    tag = secrets.token_hex(3)
    made: list[str] = []

    def member(role: str, active: bool = True) -> tuple[str, str]:
        """(member_id, email): created directly, signed up with PASSWORD when active."""
        email = f"dbtest-{tag}-{role}-{len(made)}@example.com"
        member_id = store.create_member(email, role, None, security.token_hash(secrets.token_hex(8)), "invite",
                                        datetime(2099, 1, 1, tzinfo=UTC))
        made.append(member_id)
        if active:
            store.accept_link(member_id, f"Test {role.title()}", security.hash_password(PASSWORD))
        return member_id, email

    app = create_app(FakeManager(), vapi_secret=SECRET, repo=repo,
                     console=ConsoleSettings(session_secret="s" * 32, public_base_url="https://support.example.com"))
    yield {"repo": repo, "store": store, "member": member, "made": made, "app": app, "tag": tag}

    for member_id in made:  # undo everything this module created
        repo._run("delete from case_events where member_id::text = %s", (member_id,))
        for table in ("support_tickets", "escalations"):
            repo._run(f"update {table} set owner_id = null where owner_id::text = %s", (member_id,))
        repo._run("update team_members set invited_by = null where invited_by::text = %s", (member_id,))
    repo._run("delete from team_members where email like %s", (f"dbtest-{tag}%",))
    repo.close()


def signed_in(app, email: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/console/api/login", json={"email": email, "password": PASSWORD}, headers=CSRF)
    assert response.status_code == 200, response.text
    return client


def test_invite_accept_sign_in_and_roles(env):
    _, admin_email = env["member"]("admin")
    admin = signed_in(env["app"], admin_email)
    assert admin.get("/console/api/me").json()["permissions"]["manage_admins"] is False

    assert admin.post("/console/api/team/invites", json={"email": "x@example.com", "role": "admin"},
                      headers=CSRF).status_code == 403  # admins manage support only
    assert admin.post("/console/api/team/invites", json={"email": "x@example.com", "role": "support"}).status_code == 403  # no CSRF header
    invited = admin.post("/console/api/team/invites", json={"email": f"dbtest-{env['tag']}-new@example.com",
                                                           "role": "support"}, headers=CSRF)
    assert invited.status_code == 201
    new = invited.json()
    env["made"].append(new["member"]["member_id"])
    assert new["member"]["status"] == "pending" and new["invite_url"].startswith("https://support.example.com/console/invite/")
    old_token = new["invite_url"].rsplit("/", 1)[-1]

    resent = admin.post(f"/console/api/team/{new['member']['member_id']}/resend", headers=CSRF).json()
    token = resent["invite_url"].rsplit("/", 1)[-1]
    person = TestClient(env["app"])
    assert person.get(f"/console/api/invites/{old_token}").status_code == 410  # resending cancels the old link
    assert person.get(f"/console/api/invites/{token}").json() == {"email": new["member"]["email"], "role": "support",
                                                                  "kind": "invite"}
    bad = person.post(f"/console/api/invites/{token}/accept",
                      json={"name": "Z", "password": "short", "confirm_password": "other"}, headers=CSRF)
    assert bad.status_code == 400 and set(bad.json()["fields"]) == {"name", "password", "confirm_password"}
    ok = person.post(f"/console/api/invites/{token}/accept",
                     json={"name": "Zainab Yusuf", "password": PASSWORD, "confirm_password": PASSWORD}, headers=CSRF)
    assert ok.status_code == 200 and ok.json()["member"]["status"] == "active"
    assert person.get("/console/api/me").json()["member"]["role"] == "support"  # signed in by accepting
    assert person.get(f"/console/api/invites/{token}").status_code == 410  # single use
    assert person.get("/console/api/team").status_code == 403  # support has no Team page

    admin.patch(f"/console/api/team/{new['member']['member_id']}", json={"status": "disabled"}, headers=CSRF)
    assert person.get("/console/api/me").status_code == 401  # disabling signs them out everywhere


def test_failed_sign_ins_are_vague_and_rate_limited(env):
    _, email = env["member"]("support")
    client = TestClient(env["app"])
    wrong = client.post("/console/api/login", json={"email": email, "password": "nope-nope"}, headers=CSRF)
    assert wrong.status_code == 401 and wrong.json()["detail"] == "Email or password is incorrect."
    unknown = client.post("/console/api/login", json={"email": "nobody@example.com", "password": "x"}, headers=CSRF)
    assert unknown.json() == wrong.json()  # never says which part was wrong
    for _ in range(4):
        client.post("/console/api/login", json={"email": email, "password": "nope-nope"}, headers=CSRF)
    assert client.post("/console/api/login", json={"email": email, "password": PASSWORD},
                       headers=CSRF).status_code == 429


def test_case_ownership_flow_and_reads(env):
    store, repo = env["store"], env["repo"]
    support_id, support_email = env["member"]("support")
    _, admin_email = env["member"]("admin")
    cid = f"dbtest-{env['tag']}-call"
    repo.ensure_conversation(cid, caller={"name": "Ada", "email": "ada@example.com"})
    made = cases.create_escalation(repo, cid, "payment", "Payment TXN-9001 is delayed", datetime.now(UTC),
                                   reference="TXN-9001")
    esc, ticket = made["escalation_id"], made["ticket_id"]
    try:
        support, admin = signed_in(env["app"], support_email), signed_in(env["app"], admin_email)
        listed = support.get("/console/api/cases?type=escalation&filter=unassigned").json()
        assert esc in [c["case_id"] for c in listed["cases"]]
        tickets = support.get("/console/api/cases?type=ticket&filter=open").json()["cases"]
        assert ticket not in [c["case_id"] for c in tickets]  # an escalation's ticket isn't listed twice
        everything = support.get("/console/api/cases?filter=unassigned").json()["cases"]  # one list, both kinds
        assert esc in [c["case_id"] for c in everything] and ticket not in [c["case_id"] for c in everything]

        assert support.post(f"/console/api/cases/escalation/{esc}/take", headers=CSRF).json()["case"]["owner"]["member_id"] == support_id
        assert not store.update_case("escalation", esc, owner_id=support_id, only_if="unowned_open")  # 2nd take loses
        taken = repo._run("select owner_id::text as owner, status from support_tickets where ticket_id = %s", (ticket,), "one")
        assert taken == {"owner": support_id, "status": "in progress"}  # its ticket follows the escalation
        assert support.post(f"/console/api/cases/escalation/{esc}/reopen", headers=CSRF).status_code == 403
        assert support.post(f"/console/api/cases/escalation/{esc}/resolve", json={"note": ""}, headers=CSRF).status_code == 400
        done = support.post(f"/console/api/cases/escalation/{esc}/resolve", json={"note": "Called back, settled."},
                            headers=CSRF).json()["case"]
        assert done["status"] == "closed"
        ticket_row = repo._run("select status, resolution_note from support_tickets where ticket_id = %s", (ticket,), "one")
        assert ticket_row["status"] == "closed"  # its ticket closed with it
        assert admin.post(f"/console/api/cases/escalation/{esc}/reopen", headers=CSRF).json()["case"]["status"] == "in progress"
        support.post(f"/console/api/cases/escalation/{esc}/notes", json={"text": "Customer prefers email."}, headers=CSRF)
        detail = admin.get(f"/console/api/cases/escalation/{esc}").json()
        assert [e["kind"] for e in detail["timeline"]] == ["created", "take", "resolve", "reopen", "note"]
        assert detail["related"]["reference"] == "TXN-9001" and detail["case"]["contact"]["email"] == "ada@example.com"

        conversations = admin.get(f"/console/api/conversations?search={cid}").json()
        assert conversations["conversations"][0]["outcome"] == "handed_to_specialist"
        assert conversations["pagination"] == {"page": 1, "page_size": 25, "total": 1}
        past_end = admin.get(f"/console/api/conversations?search={cid}&page=2").json()
        assert past_end["conversations"] == [] and past_end["pagination"]["total"] == 1  # real total, not a 404
        filtered = admin.get(f"/console/api/conversations?search={cid}&outcome=answered").json()
        assert filtered["pagination"]["total"] == 0 and filtered["counts"]["handed_to_specialist"] == 1
        assert admin.get("/console/api/conversations?page_size=101").status_code == 400
        assert admin.get("/console/api/cases?page=0").status_code == 400
        rows, _ = store.conversation_page(None, None, 1, 100)
        assert all(r["outcome"] == views.outcome(r) for r in rows)  # the SQL rule matches the Python one
        customers = admin.get("/console/api/customers?page_size=2").json()
        assert len(customers["customers"]) == 2 and customers["pagination"]["total"] >= 5
        assert "total_rows" not in customers["customers"][0]
        page = admin.get(f"/console/api/cases?filter=open&page_size=100").json()
        mine = next(c for c in page["cases"] if c["case_id"] == esc)
        assert mine["ticket_id"] == ticket and page["pagination"]["total"] == page["counts"]["open"]
        assert admin.get(f"/console/api/conversations/{cid}").json()["cases"][0]["case_id"] == esc
        assert admin.get("/console/api/customers/CUS-1001").json()["transactions"]
        summary = admin.get("/console/api/summary").json()
        assert {"conversations_today", "open_cases", "unassigned"} <= set(summary["kpis"])
        report = admin.get("/console/api/analytics?from=2026-09-01&to=2026-10-31").json()
        assert report["series"]["bucket"] == "week" and "answered" in report["ended"]
        assert admin.get("/console/api/analytics?from=2026-10-31&to=2026-09-01").status_code == 400
        assert admin.get("/console/api/new?since=2000-01-01T00:00:00Z").json()["count"] >= 1
        assert TestClient(env["app"]).get("/console/api/cases").status_code == 401
    finally:
        repo._run("delete from case_events where case_id in (%s, %s)", (esc, ticket))
        for table in ("escalations", "support_tickets", "conversation_events", "tool_calls", "conversation_turns",
                      "conversations"):
            repo._run(f"delete from {table} where conversation_id = %s", (cid,))
