import asyncio
from datetime import UTC, date, datetime

from customer_support_agent.mcp_server.tools import accounts, cases
from customer_support_agent.mcp_server.tools.common import run_tool
from tests.mcp_server.fake_repo import FakeRepository

import pytest

from customer_support_agent.agent import spoken
from customer_support_agent.mcp_server.tools import common


@pytest.fixture(autouse=True)
def fresh_call_memory():
    """What Bex last said and pending read-backs are per call, in memory: start each test clean."""
    spoken._last.clear()
    common._pending.clear()
    yield
    spoken._last.clear()
    common._pending.clear()

TODAY = date(2026, 10, 1)
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)  # Thursday


def test_verification_checks_both_fields_and_caps_attempts():
    repo = FakeRepository()
    said = accounts.lookup_customer(repo, "c1", "amara at L-A-G-O-S ledger dot example", "AccraStack")
    assert (said["error"], said["say"]) == ("confirm_email", "Just to confirm, that's amara at lagosledger dot example. Is that right?")
    assert repo.conversations["c1"]["verification_attempts"] == 0  # not confirmed yet: no attempt used
    wrong = accounts.lookup_customer(repo, "c1", "amara at lagosledger dot example", "AccraStack", email_confirmed=True)
    assert (wrong["found"], wrong["attempts_left"]) == (False, 1) and "letter by letter" in wrong["hint"]
    spoken.remember("c1", "Just to confirm, that's amara at lagosledger dot example. Is that right?")
    ok = accounts.lookup_customer(repo, "c1", "amara at lagosledger dot example", "Lagos Ledger", email_confirmed=True)
    assert (ok["found"], ok["plan"], repo.conversations["c1"]["verified_customer_id"]) == (True, "Growth", "CUS-1001")
    assert "contact_email" not in ok  # details held on file never reach the model

    repo2 = FakeRepository()
    spoken.remember("c2", "Just to confirm, that's efua at accrastack dot example?")  # Bex read it back herself
    for company in ("Wrong Co", "Wrong Co", "Other Co"):  # the exact repeat doesn't use up the retry
        accounts.lookup_customer(repo2, "c2", "efua@accrastack.example", company, email_confirmed=True)
    assert accounts.lookup_customer(repo2, "c2", "efua@accrastack.example", "AccraStack",
                                    email_confirmed=True)["error"] == "limit_reached"
    assert [e[1] for e in repo2.events] == ["verification_failed"]  # logged by the tool, once

    form = FakeRepository()
    form.ensure_conversation("c3", caller={"email": "amara@lagosledger.example"})
    assert accounts.lookup_customer(form, "c3", None, "Lagos Ledger")["found"] is True  # email from the form


def test_lookups_return_only_status_and_next_step():
    repo = FakeRepository()
    txn = accounts.lookup_transaction(repo, "c1", "T X N nine zero zero one", TODAY)
    assert txn == {"found": True, "reference": "TXN-9001", "status": "delayed",
                   "say": "I'm sorry, that payment is taking a bit longer than usual.", "next_step": "escalate"}  # processing, ETA passed
    payout = accounts.lookup_payout(repo, "c1", None, "TXN-9003", TODAY)  # by its transaction reference
    assert (payout["reference"], payout["status"], payout["next_step"]) == ("PAY-7002", "under review", "escalate")
    assert "failure_reason" not in payout and "amount" not in txn
    assert accounts.lookup_transaction(repo, "c1", "payout 7002", TODAY)["reference"] == "PAY-7002"  # routed
    assert accounts.lookup_transaction(repo, "c1", "TXN-1234", TODAY)["found"] is False
    assert accounts.lookup_transaction(repo, "c1", "the blue one", TODAY)["error"] == "invalid_input"


def test_guessing_references_stops_lookups_and_other_customers_references_are_flagged():
    repo = FakeRepository()
    for guess in ("TXN-1111", "TXN-2222", "TXN-3333"):
        assert accounts.lookup_transaction(repo, "c1", guess, TODAY)["found"] is False
    assert accounts.lookup_transaction(repo, "c1", "TXN-9001", TODAY)["error"] == "limit_reached"  # even a real one
    assert [e[1] for e in repo.events] == ["sensitive_request"]  # "possible reference guessing", logged once

    verified = FakeRepository()
    spoken.remember("c2", "That's efua at accrastack dot example, right?")
    accounts.lookup_customer(verified, "c2", "efua@accrastack.example", "AccraStack", email_confirmed=True)  # CUS-1003
    assert accounts.lookup_transaction(verified, "c2", "TXN-9001", TODAY)["found"] is True  # status only, as anyone
    assert [e[2] for e in verified.events] == ["Verified caller looked up another customer's reference"]


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
    spoken.remember("c1", "That's efua at accrastack dot example, right?")
    accounts.lookup_customer(repo, "c1", "efua@accrastack.example", "AccraStack", email_confirmed=True)
    result = cases.create_escalation(repo, "c1", "account", "Account restricted", NOW)
    escalation = repo.escalation_rows[0]
    assert (escalation["user_email"], escalation["verified"], escalation["ticket_id"]) == (
        "efua@accrastack.example", True, result["ticket_id"])  # contact from the record, not asked for
    ticket = next(t for t in repo.ticket_rows if t["ticket_id"] == result["ticket_id"])
    assert (ticket["category"], ticket["caller_verified"]) == ("account", True)
    assert repo.events[0][1] == "escalation_created"
    assert "next" in result  # first step: Bex asks whether they'd like a call back or email

    by_email = cases.create_escalation(repo, "c1", "account", "Account restricted", NOW, contact_method="email")
    assert by_email["follow_up_summary"] == "Lovely, a specialist will email you."


def test_a_callback_needs_a_number_and_a_window_in_local_time():
    repo = FakeRepository()
    repo.ensure_conversation("c1", caller={"name": "Ada", "email": "ada@example.com"})
    first = cases.create_escalation(repo, "c1", "dispute", "Refund", NOW, reference="TXN-9004")
    ticket = repo.ticket_rows[0]
    assert (ticket["reference"], ticket["customer_id"], ticket["caller_verified"]) == ("TXN-9004", "CUS-1003", False)

    weekend = cases.create_escalation(repo, "c1", "dispute", "Refund", NOW, contact_method="call",
                                      callback_day="saturday", callback_time="morning", callback_place="Lagos",
                                      callback_phone="0814 346 3800")
    assert weekend["error"] == "outside_hours"  # the time is checked before anything is confirmed
    call = dict(contact_method="call", callback_day="tomorrow", callback_time="10am", callback_place="West Africa Time",
                callback_phone="081-4 346 3800")  # a local number: the place gives the country code
    unconfirmed = cases.create_escalation(repo, "c1", "dispute", "Refund", NOW, **call)
    assert unconfirmed["say"] == ("Just to confirm: 0814 346 3800, on Friday 2 October, between 10am and 12pm "
                                  "Lagos time. Is that right?")  # one read-back: number and time together
    assert not repo.escalation_rows[0].get("callback_phone")  # nothing saved until they say yes
    timed = cases.create_escalation(repo, "c1", "dispute", "Refund", NOW, phone_confirmed=True, **call)
    assert (timed["created"], timed["escalation_id"]) == (False, first["escalation_id"])  # same escalation, updated
    assert timed["follow_up_summary"] == "Lovely, a specialist will call you on Friday 2 October, between 10am and 12pm Lagos time."
    no_place = cases.create_escalation(repo, "c1", "dispute", "Refund", NOW, contact_method="call", callback_time="any",
                                       callback_phone="0814 346 3800")
    assert no_place["error"] == "invalid_input" and "country code" in no_place["hint"]  # nowhere to take it from
    escalation = repo.escalation_rows[0]
    assert (escalation["contact_method"], escalation["callback_phone"], escalation["call_booked"]) == (
        "call", "+2348143463800", True)  # the local 0 dropped after +234

    form_phone = FakeRepository()
    form_phone.ensure_conversation("c2", caller={"name": "Ada", "email": "ada@example.com", "phone": "+2348031234567"})
    any_time = cases.create_escalation(form_phone, "c2", "other", "Wants a call", NOW, contact_method="call",
                                       callback_time="any")
    assert "as soon as one is free" in any_time["follow_up_summary"]  # no city needed for "any time"
    assert form_phone.escalation_rows[0]["callback_phone"] == "+2348031234567"  # from the form, never spoken


def test_escalation_contact_falls_back_to_the_form_then_what_was_said():
    form = FakeRepository()
    form.ensure_conversation("c1", caller={"name": "Tunde", "email": "tunde@example.com"})
    cases.create_escalation(form, "c1", "payment", "Invoice payment failed", NOW)
    assert (form.escalation_rows[0]["user_name"], form.escalation_rows[0]["verified"]) == ("Tunde", False)
    assert form.ticket_rows  # scenario 6: a ticket exists even with no reference

    spoken = FakeRepository()
    assert cases.create_escalation(spoken, "c2", "dispute", "Refund", NOW)["error"] == "needs_contact"
    said = cases.create_escalation(spoken, "c2", "dispute", "Refund", NOW, "Ada", "ada at example dot com")
    assert (said["error"], said["say"]) == ("confirm_email", "Just to confirm, that's ada at example dot com. Is that right?")
    assert not spoken.escalation_rows
    assert cases.create_escalation(spoken, "c2", "dispute", "Refund", NOW, "Ada", "ada at example dot com",
                                   email_confirmed=True)["created"]


def test_the_email_flow_uses_the_form_or_asks_and_confirms_once():
    form = FakeRepository()
    form.ensure_conversation("c1", caller={"name": "Ada", "email": "ada@example.com"})
    made = cases.create_escalation(form, "c1", "payment", "Delayed", NOW, reference="TXN-9001")
    assert made["created"] and made["next"]  # no questions about contact: straight to "call or email?"
    assert (form.escalation_rows[0]["user_email"], form.escalation_rows[0]["contact_method"]) == ("ada@example.com", "email")

    spoken = FakeRepository()  # no form: ask, confirm once, then create
    assert cases.create_escalation(spoken, "c2", "payment", "Delayed", NOW)["error"] == "needs_contact"
    assert cases.create_escalation(spoken, "c2", "payment", "Delayed", NOW, "Ada", "ada@example.com")["error"] == "confirm_email"
    made = cases.create_escalation(spoken, "c2", "payment", "Delayed", NOW, "Ada", "ada@example.com", email_confirmed=True)
    assert made["created"] and spoken.escalation_rows[0]["contact_method"] == "email"  # email is the default


def test_impossible_callback_and_bad_events_are_explained():
    repo = FakeRepository()
    phone = "+2348031234567"
    weekend = cases.create_escalation(repo, "c1", "other", "Wants a call", NOW, "Ada", "ada@example.com",
                                      contact_method="call", callback_place="Lagos", callback_day="saturday",
                                      callback_time="morning", callback_phone=phone)
    assert weekend["error"] == "outside_hours" and "weekdays 9am to 7pm Lagos time" in weekend["hint"]
    no_place = cases.create_escalation(repo, "c1", "other", "Wants a call", NOW, "Ada", "ada@example.com",
                                       contact_method="call", callback_time="3pm", callback_phone=phone)
    assert no_place["error"] == "invalid_input"
    assert cases.create_escalation(repo, "c1", "other", "x", NOW, contact_method="pigeon")["error"] == "invalid_input"
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
        def create_ticket(self, *args, **kwargs):
            raise RepositoryUnavailable("insert failed")

    repo = WriteFails()
    result = asyncio.run(run_tool(repo, "c1", "create_support_ticket", "p", "s",
                                  lambda: cases.create_support_ticket(repo, "c1", "payment", "high", "x", "TXN-9004"),
                                  exclusive=True))
    assert result["error"] == "unavailable" and "ticket_id" not in result


def test_a_lookup_that_needs_people_creates_the_escalation_or_ticket_itself():
    form = FakeRepository()
    form.ensure_conversation("c1", caller={"name": "Ada", "email": "ada@example.com"})
    delayed = accounts.lookup_transaction(form, "c1", "TXN-9001", TODAY, NOW)  # processing, ETA passed
    assert delayed["say"].startswith("I'm sorry, that payment") and delayed["escalation_id"]
    assert form.escalation_rows[0]["user_email"] == "ada@example.com"  # contact from the form, nobody asked
    assert form.ticket_rows[0]["reference"] == "TXN-9001" and "call back or an email" in delayed["next"]

    failed = accounts.lookup_transaction(form, "c1", "TXN-9004", TODAY, NOW)  # failed transaction: a ticket
    assert failed["ticket_id"] and "logged it" in failed["next"]

    nobody = FakeRepository()  # no form, not verified: the lookup says to ask, then escalate
    asked = accounts.lookup_transaction(nobody, "c2", "TXN-9001", TODAY, NOW)
    assert "escalation_id" not in asked and "name and email" in asked["next"]


def test_one_read_back_only_whoever_reads_it():
    repo = FakeRepository()
    repo.ensure_conversation("c1", caller={"name": "Ada", "email": "ada@example.com"})
    cases.create_escalation(repo, "c1", "dispute", "Refund", NOW)
    call = dict(contact_method="call", callback_day="tomorrow", callback_time="10am", callback_place="Lagos",
                callback_phone="0814 346 3800")
    spoken.remember("c1", "Just to confirm, the number is 0814-346-3800, tomorrow at 10. Is that right?")
    done = cases.create_escalation(repo, "c1", "dispute", "Refund", NOW, phone_confirmed=True, **call)
    assert "error" not in done  # Bex read it back herself and they agreed: no second read-back

    other = FakeRepository()
    other.ensure_conversation("c2", caller={"name": "Ada", "email": "ada@example.com"})
    cases.create_escalation(other, "c2", "dispute", "Refund", NOW)
    spoken.remember("c2", "Just to confirm, the number is 0814-346-3900?")  # she read out a different number
    again = cases.create_escalation(other, "c2", "dispute", "Refund", NOW, phone_confirmed=True, **call)
    assert again["error"] == "confirm_phone"  # what gets stored must be what the caller heard
