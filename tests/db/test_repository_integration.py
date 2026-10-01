"""The real SQL against the real Supabase, in the throwaway `test` schema (never the real records).

Skipped unless asked for: RUN_DB_TESTS=1 poetry run pytest tests/db
Needs DATABASE_URL in .env and the test schema created once: DATABASE_SCHEMA=test poetry run relaypay-db
Each test uses its own conversation ID and deletes its rows afterwards.
"""

import os
import secrets
from datetime import UTC, datetime

import pytest

from customer_support_agent.db.repository import Repository, RepositoryUnavailable
from customer_support_agent.mcp_server.tools import accounts, cases

pytestmark = pytest.mark.skipif(os.environ.get("RUN_DB_TESTS") != "1",
                                reason="database tests run only with RUN_DB_TESTS=1")

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
TABLES = ("escalations", "support_tickets", "conversation_events", "tool_calls", "retrieval_logs",
          "conversation_turns", "conversations")


@pytest.fixture
def repo():
    from dotenv import find_dotenv, load_dotenv

    from customer_support_agent.config import load_database_url

    load_dotenv(find_dotenv(usecwd=True))
    repository = Repository(load_database_url(), schema="test")  # always the throwaway schema
    repository.open()
    yield repository
    repository.close()


@pytest.fixture
def cid(repo):
    conversation_id = f"dbtest-{secrets.token_hex(4)}"
    yield conversation_id
    for table in TABLES:
        repo._run(f"delete from {table} where conversation_id = %s", (conversation_id,))


def test_database_errors_come_back_as_repository_unavailable(repo, cid):
    with pytest.raises(RepositoryUnavailable):  # never a raw psycopg error
        repo._run("select * from no_such_table")
    row = repo.ensure_conversation(cid, model="m", caller={"email": "ada@example.com"})
    assert (row["conversation_id"], row["caller_email"], row["final_status"]) == (cid, "ada@example.com", "in_progress")


def test_an_escalation_and_its_event_are_saved_together_or_not_at_all(repo, cid):
    repo.ensure_conversation(cid)
    ticket, _ = repo.create_ticket(cid, None, "other", "high", "x", "")
    values = {"conversation_id": cid, "ticket_id": ticket, "customer_id": None, "user_name": "Ada",
              "user_email": "ada@example.com", "category": "other", "reason": "x", "verified": False,
              "call_booked": False, "preferred_time_raw": None}
    with pytest.raises(RepositoryUnavailable):
        repo.create_escalation(values, None, {})  # the event can't be saved (no summary)...
    assert repo.escalations(cid) == []  # ...so the escalation wasn't either

    escalation_id, created = repo.create_escalation(values, "other: x", {})
    events = repo._run("select event_type, metadata from conversation_events where conversation_id = %s", (cid,), "all")
    assert created and [(e["event_type"], e["metadata"]["escalation_id"]) for e in events] == [
        ("escalation_created", escalation_id)]


def test_the_tools_keep_accurate_records_on_the_real_database(repo, cid):
    repo.ensure_conversation(cid, caller={"name": "Efua", "email": "efua@accrastack.example"})
    assert accounts.lookup_customer(repo, cid, None, "Wrong Co")["found"] is False  # form email used
    assert accounts.lookup_customer(repo, cid, None, "Wrong Co")["attempts_left"] == 1  # repeat not counted
    assert accounts.lookup_customer(repo, cid, None, "Accra Stack")["customer_id"] == "CUS-1003"

    first = cases.create_support_ticket(repo, cid, "payment", "high", "Failed", "TXN-9004")
    again = cases.create_support_ticket(repo, cid, "payment", "high", "Failed again", "txn 9004")
    assert (again["ticket_id"], again["created"]) == (first["ticket_id"], False)

    lookup = accounts.lookup_transaction(repo, cid, "TXN-9001", NOW.date())  # another customer's: status, flagged
    assert (lookup["found"], lookup["status"]) == (True, "delayed")
    assert accounts.lookup_transaction(repo, cid, "TXN-1111", NOW.date())["found"] is False
    assert repo.lookup_reference(cid, "transaction", "TXN-1111")[0] == 1  # the miss was counted

    escalation = cases.create_escalation(repo, cid, "account", "Restricted", NOW, reference="TXN-9004")
    assert escalation["ticket_id"] and escalation["created"]
    call = cases.create_escalation(repo, cid, "account", "Restricted", NOW, contact_method="call",
                                   callback_day="monday", callback_time="afternoon", callback_place="Accra",
                                   callback_phone="+233 24 412 3456", phone_confirmed=True)
    saved = repo.escalations(cid)[0]
    assert (saved["contact_method"], saved["callback_phone"], saved["call_booked"]) == ("call", "+233244123456", True)
    assert "Accra time" in call["follow_up_summary"]
    repo.close_conversation(cid, "Summary.")
    conv = repo._run("select final_status, summary, verification_attempts from conversations where conversation_id = %s",
                     (cid,), "one")
    assert (conv["final_status"], conv["summary"], conv["verification_attempts"]) == ("escalated", "Summary.", 2)  # wrong, (repeat skipped), right
