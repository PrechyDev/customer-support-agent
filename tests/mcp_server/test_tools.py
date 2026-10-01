import asyncio
from datetime import UTC, date, datetime

from customer_support_agent.mcp_server.tools import accounts, cases
from customer_support_agent.mcp_server.tools.common import run_tool
from tests.mcp_server.fake_repo import FakeRepository

TODAY = date(2026, 10, 1)
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)  # Thursday


def test_verification_checks_both_fields_and_caps_attempts():
    repo = FakeRepository()
    wrong = accounts.lookup_customer(repo, "c1", "amara at lagosledger dot example", "AccraStack")
    assert wrong == {"found": False, "attempts_left": 1, "hint": "Ask them to repeat the email and company once."}
    ok = accounts.lookup_customer(repo, "c1", "amara at lagosledger dot example", "Lagos Ledger")
    assert (ok["found"], ok["plan"], repo.conversations["c1"]["verified_customer_id"]) == (True, "Growth", "CUS-1001")
    assert "contact_email" not in ok  # details held on file never reach the model

    repo2 = FakeRepository()
    for company in ("Wrong Co", "Wrong Co", "Other Co"):  # the exact repeat doesn't use up the retry
        accounts.lookup_customer(repo2, "c2", "efua@accrastack.example", company)
    assert accounts.lookup_customer(repo2, "c2", "efua@accrastack.example", "AccraStack")["error"] == "limit_reached"
    assert [e[1] for e in repo2.events] == ["verification_failed"]  # logged by the tool, once

    form = FakeRepository()
    form.ensure_conversation("c3", caller={"email": "amara@lagosledger.example"})
    assert accounts.lookup_customer(form, "c3", None, "Lagos Ledger")["found"] is True  # email from the form


def test_lookups_return_only_status_and_next_step():
    repo = FakeRepository()
    txn = accounts.lookup_transaction(repo, "c1", "T X N nine zero zero one", TODAY)
    assert txn == {"found": True, "reference": "TXN-9001", "status": "delayed",
                   "say": "It's taking longer than usual.", "next_step": "escalate"}  # processing, ETA passed
    payout = accounts.lookup_payout(repo, "c1", None, "TXN-9003", TODAY)  # by its transaction reference
    assert (payout["reference"], payout["status"], payout["next_step"]) == ("PAY-7002", "under review", "escalate")
    assert "failure_reason" not in payout and "amount" not in txn
    assert accounts.lookup_transaction(repo, "c1", "payout 7002", TODAY)["reference"] == "PAY-7002"  # routed
    assert accounts.lookup_transaction(repo, "c1", "TXN-1234", TODAY)["found"] is False
    assert accounts.lookup_transaction(repo, "c1", "the blue one", TODAY)["error"] == "invalid_input"


def test_tickets_need_someone_to_follow_up_and_never_duplicate():
    repo = FakeRepository()
    assert cases.create_support_ticket(repo, "c1", "payment", "high", "Invoice failed")["error"] == "needs_contact"
    first = cases.create_support_ticket(repo, "c1", "payment", "high", "Payout failed", "TXN-9004")
    again = cases.create_support_ticket(repo, "c1", "payment", "high", "Payout failed again", "txn 9004")
    assert (first["created"], again["created"], again["ticket_id"]) == (True, False, first["ticket_id"])
    assert repo.ticket_rows[0]["customer_id"] == "CUS-1003"  # owner taken from the record, not the model
    assert cases.create_support_ticket(repo, "c1", "money", "high", "x")["error"] == "invalid_input"


def test_escalation_uses_verified_contact_links_a_ticket_and_logs_an_event():
    repo = FakeRepository()
    accounts.lookup_customer(repo, "c1", "efua@accrastack.example", "AccraStack")
    result = cases.create_escalation(repo, "c1", "account", "Account restricted", NOW)
    escalation = repo.escalation_rows[0]
    assert (escalation["user_email"], escalation["verified"], escalation["ticket_id"]) == (
        "efua@accrastack.example", True, result["ticket_id"])  # contact from the record, not asked for
    assert next(t for t in repo.ticket_rows if t["ticket_id"] == result["ticket_id"])["category"] == "account"
    assert repo.events[0][1] == "escalation_created"
    assert result["follow_up_summary"] == "A specialist will follow up with you by email."

    timed = cases.create_escalation(repo, "c1", "account", "Account restricted", NOW, callback_place="Accra",
                                    callback_day="tomorrow", callback_time="morning")  # adds a time to the same one
    assert (timed["created"], timed["escalation_id"]) == (False, result["escalation_id"])
    assert "Friday 2 October, between 9am and 12pm Accra time" in timed["follow_up_summary"]
    assert escalation["call_booked"] is True


def test_escalation_contact_falls_back_to_the_form_then_what_was_said():
    form = FakeRepository()
    form.ensure_conversation("c1", caller={"name": "Tunde", "email": "tunde@example.com"})
    cases.create_escalation(form, "c1", "payment", "Invoice payment failed", NOW)
    assert (form.escalation_rows[0]["user_name"], form.escalation_rows[0]["verified"]) == ("Tunde", False)
    assert form.ticket_rows  # scenario 6: a ticket exists even with no reference

    spoken = FakeRepository()
    assert cases.create_escalation(spoken, "c2", "dispute", "Refund", NOW)["error"] == "invalid_input"
    assert cases.create_escalation(spoken, "c2", "dispute", "Refund", NOW, "Ada", "ada at example dot com")["created"]


def test_impossible_callback_and_bad_events_are_explained():
    repo = FakeRepository()
    weekend = cases.create_escalation(repo, "c1", "other", "Wants a call", NOW, "Ada", "ada@example.com",
                                      callback_place="Lagos", callback_day="saturday", callback_time="morning")
    assert weekend["error"] == "outside_hours" and "weekdays 9am to 7pm Lagos time" in weekend["hint"]
    no_place = cases.create_escalation(repo, "c1", "other", "Wants a call", NOW, "Ada", "ada@example.com",
                                       callback_time="3pm")
    assert no_place["error"] == "invalid_input"
    assert cases.log_conversation_event(repo, "c1", "gossip", "x")["error"] == "invalid_input"
    assert cases.log_conversation_event(repo, "c1", "injection_attempt", "Asked for the system prompt") == {"logged": True}


def test_database_down_gives_a_clean_error_and_the_call_is_still_logged():
    repo = FakeRepository(down=True)

    async def scenario():
        result = await run_tool(repo, "c1", "lookup_transaction", "status", "ref=TXN-9001",
                                lambda: accounts.lookup_transaction(repo, "c1", "TXN-9001", TODAY))
        await asyncio.sleep(0.05)  # let the background log run
        return result

    result = asyncio.run(scenario())
    assert result["error"] == "unavailable" and "dashboard" in result["hint"]
    assert repo.tool_calls and repo.tool_calls[0][5] == "error"


def test_parallel_escalations_in_one_turn_cannot_pass_the_cap():
    repo = FakeRepository()
    repo.ensure_conversation("c1", caller={"name": "Ada", "email": "ada@example.com"})

    async def scenario():
        def escalate(category):
            return lambda: cases.create_escalation(repo, "c1", category, "x", NOW)
        return await asyncio.gather(*(run_tool(repo, "c1", "create_escalation", "p", "s", escalate(c), exclusive=True)
                                      for c in ("account", "dispute", "payment")))

    results = asyncio.run(scenario())
    assert len(repo.escalation_rows) == 2 and sum("error" in r for r in results) == 1  # cap is 2


def test_a_capped_tool_arriving_late_still_waits_its_turn():
    """The case the lock once missed: C arrives while B (which waited for A) is still running."""
    import threading
    import time

    from customer_support_agent.mcp_server.tools import common

    running, most, guard = [0], [0], threading.Lock()

    def work():
        with guard:
            running[0] += 1
            most[0] = max(most[0], running[0])
        time.sleep(0.05)
        with guard:
            running[0] -= 1
        return {"ok": True}

    async def scenario():
        a = asyncio.create_task(common._work("c1", work, exclusive=True))
        b = asyncio.create_task(common._work("c1", work, exclusive=True))  # waits for A
        await a
        c = asyncio.create_task(common._work("c1", work, exclusive=True))  # arrives while B runs
        await asyncio.gather(b, c)

    asyncio.run(scenario())
    assert most[0] == 1 and common._call_locks == {}  # never two at once, and nothing left behind


def test_a_failed_ticket_write_never_returns_a_ticket_id():
    from customer_support_agent.db.repository import RepositoryUnavailable

    class WriteFails(FakeRepository):
        def create_ticket(self, *args):
            raise RepositoryUnavailable("insert failed")

    repo = WriteFails()
    result = asyncio.run(run_tool(repo, "c1", "create_support_ticket", "p", "s",
                                  lambda: cases.create_support_ticket(repo, "c1", "payment", "high", "x", "TXN-9004"),
                                  exclusive=True))
    assert result["error"] == "unavailable" and "ticket_id" not in result
