"""lookup_customer, lookup_transaction, lookup_payout (SPECS §3, §5, §9).

Identity always comes from the conversation record, never from the model. Lookups return only
what the caller may hear: no amounts, no other customers, no failure reasons.
"""

import hashlib
from datetime import date, datetime
from typing import Any

from customer_support_agent.domain.normalise import normalise_company, normalise_email, parse_reference, spoken_email
from customer_support_agent.domain.status import caller_status
from customer_support_agent.agent.spoken import heard_text
from customer_support_agent.mcp_server.tools import cases
from customer_support_agent.mcp_server.tools.common import (
    MAX_LOOKUP_MISSES,
    MAX_VERIFICATION_ATTEMPTS,
    confirmed,
    error,
)

LOOKUP_CUSTOMER = (
    "Verify the caller and get their account summary. Needs BOTH the email and the company name. Leave out "
    "either one to use what the caller typed in the pre-call form. A spoken email returns confirm_email first: say "
    "its 'say' line and call again with email_confirmed true once they agree (only a confirmed email counts as an "
    "attempt). Returns found=false on any mismatch (never say which part failed). Max 2 attempts per call, then "
    "escalate as 'identity not verified'."
)
LOOKUP_TRANSACTION = (
    "Status of one transaction, from the reference the caller gives (pass exactly what they said). "
    "Returns only a status, a line you can say ('say'), and next_step. If the status needs people, it creates the "
    "escalation or ticket itself and says what to do in 'next'. Always say 'say' first. Never guess a reference."
)
LOOKUP_PAYOUT = (
    "Status of one payout, by its payout reference or its transaction reference. Returns only a status, "
    "a line you can say, and next_step; like lookup_transaction it creates the escalation itself when needed and "
    "says what to do in 'next'. Never state a failure reason."
)


RESTRICTED_LINE = ("Your account is restricted at the moment, and a specialist needs to go through it with you, "
                   "so I've passed it to them.")


def _verified_summary(repo: Any, cid: str, c: dict, now: datetime | None) -> dict[str, Any]:
    """Plan and statuses only. support_notes never reach the model (changed 01-10: an eval run heard Bex repeat
    CUS-1003's "under compliance review"); what they mean is decided here instead. A restricted account, or one
    whose verification needs review, always goes to a specialist, so the lookup creates the escalation itself."""
    summary = {"found": True, "customer_id": c["customer_id"], "company_name": c["company_name"], "plan": c["plan"],
               "account_status": c["account_status"], "kyc_status": c["kyc_status"]}
    if now is None or not (c["account_status"] == "restricted" or c["kyc_status"] == "review required"):
        return summary
    made = cases.create_escalation(repo, cid, "account", "Account restricted: the customer needs a specialist", now)
    if "escalation_id" not in made:
        return {**summary, "next": "Say the account needs a specialist, then: " + made.get("hint", "offer one.")}
    return {**summary, "say": RESTRICTED_LINE, "escalation_id": made["escalation_id"], "ticket_id": made["ticket_id"],
            "next": "Say the plan if they asked for it, then the 'say' line, then ask whether they'd like a call back "
                    "or an email. You don't know why it's restricted: if asked, the specialist will go through it."}


def lookup_customer(repo: Any, cid: str, email: str | None, company_name: str | None,
                    email_confirmed: bool = False, now: datetime | None = None) -> dict[str, Any]:
    conversation = repo.ensure_conversation(cid) or {}
    if conversation.get("verified_customer_id"):  # already verified this call: no new attempt
        return _verified_summary(repo, cid, repo.customer(conversation["verified_customer_id"]), now)
    if (conversation.get("verification_attempts") or 0) >= MAX_VERIFICATION_ATTEMPTS:
        return error("limit_reached", "Too many attempts. Don't try again: escalate as 'identity not verified'.")

    email_was_spoken = bool(email)  # the form's email was typed; a spoken one may be misheard
    email = email or conversation.get("caller_email")  # what was said wins; otherwise the pre-call form
    company_name = company_name or conversation.get("caller_company")
    wanted_email, wanted_company = normalise_email(email), normalise_company(company_name)
    if not wanted_email or not wanted_company:
        return error("invalid_input", "Need both a valid email and the company name. Ask for whichever is missing.")
    heard = heard_text(cid, spoken_email(wanted_email))  # only the spelled read-back counts (see spoken_email)
    if email_was_spoken and not confirmed(cid, "email", wanted_email, email_confirmed, heard):  # misheard: no attempt
        return {"error": "confirm_email", "say": f"Just to confirm, that's {spoken_email(wanted_email)}. Is that right?",
                "hint": "Say the line; if they agree, call again with email_confirmed true. If not, ask them to "
                        "spell it letter by letter."}

    fingerprint = hashlib.sha256(f"{wanted_email}|{wanted_company}".encode()).hexdigest()
    if fingerprint == conversation.get("last_verification_try"):  # same details again: not a new attempt
        left = MAX_VERIFICATION_ATTEMPTS - (conversation.get("verification_attempts") or 0)
        return {"found": False, "attempts_left": max(left, 0),
                "hint": "Those are the same details that didn't match. Ask the caller to say their email and "
                        "company again, and only retry with what they say."}

    attempts = repo.record_verification_attempt(cid, fingerprint)
    customer = repo.customer_by_email(wanted_email)
    if not customer or normalise_company(customer["company_name"]) != wanted_company:
        left = MAX_VERIFICATION_ATTEMPTS - attempts
        if left <= 0:  # logged here, so the record never depends on the model remembering
            repo.log_event(cid, "verification_failed", f"Email and company didn't match after {attempts} attempts")
        return {"found": False, "attempts_left": max(left, 0),
                "hint": "Ask them to spell the email letter by letter and confirm the company, then try once more."
                if left > 0
                else "Don't try again: escalate as 'identity not verified'."}
    repo.mark_verified(cid, customer["customer_id"])
    return _verified_summary(repo, cid, customer, now)


def _status_result(kind: str, ref: str, record: dict, due_field: str, today: date) -> dict[str, Any]:
    st = caller_status(kind, record["status"], record.get(due_field), today)
    return {"found": True, "reference": ref, "status": st.status, "say": st.line, "next_step": st.next_step}


def _lookup(repo: Any, cid: str, kind: str, ref: str) -> tuple[dict | None, dict | None]:
    """(record, error). Guards against someone guessing references: after MAX_LOOKUP_MISSES references
    not found on one call, lookups stop. A verified caller looking up someone else's reference is
    logged (they still hear only the status, as anyone would)."""
    misses, verified, record = repo.lookup_reference(cid, kind, ref)
    if misses >= MAX_LOOKUP_MISSES:
        return None, error("limit_reached", "Several references weren't found on this call, so no more lookups. "
                                            "Suggest they check the reference and contact support through their "
                                            "RelayPay dashboard.")
    if record is None:
        if repo.record_lookup_miss(cid) >= MAX_LOOKUP_MISSES:
            repo.log_event(cid, "sensitive_request", f"Possible reference guessing: {MAX_LOOKUP_MISSES} references "
                                                     f"not found on this call", {"last_reference": ref})
        return None, None
    if verified and record.get("customer_id") != verified:
        repo.log_event(cid, "sensitive_request", "Verified caller looked up another customer's reference",
                       {"reference": ref})
    return record, None


def _malformed(repo: Any, cid: str, raw: str | None) -> dict[str, Any]:
    """A reference that isn't in the right shape counts toward the guessing limit too ("TXN-33333")."""
    if raw and raw.strip():
        misses = repo.record_lookup_miss(cid)
        if misses > MAX_LOOKUP_MISSES:
            return error("limit_reached", "Several references weren't found on this call, so no more lookups. "
                                          "Suggest they check the reference and contact support through their "
                                          "RelayPay dashboard.")
        if misses == MAX_LOOKUP_MISSES:
            repo.log_event(cid, "sensitive_request", f"Possible reference guessing: {MAX_LOOKUP_MISSES} references "
                                                     f"not found on this call", {"last_reference": raw[:40]})
    return error("invalid_input", "That doesn't sound like a reference. Ask them to repeat it once.")


def _not_found(ref: str) -> dict[str, Any]:
    return {"found": False, "reference": ref,
            "hint": "Say you couldn't find it; ask them to repeat it once, then offer a ticket."}


def _act_on(repo: Any, cid: str, result: dict[str, Any], now: datetime | None) -> dict[str, Any]:
    """A status that needs people acts straight away, in code (SPECS §5, §6): "escalate" creates the escalation
    and its ticket, "ticket" creates the ticket. Bex then has one result to speak from and nothing to forget
    (in voice tests she skipped the second tool call, or her status line was lost before it)."""
    step, ref = result.get("next_step"), result.get("reference")
    if now is None or step not in ("escalate", "ticket"):
        return result
    thing = "Payment" if ref.startswith("TXN-") else "Payout"
    reason = f"{thing} {ref} is {result['status']}"
    if step == "ticket":
        made = cases.create_support_ticket(repo, cid, "payment", "high", reason, ref)
        if "ticket_id" in made:
            return {**result, "ticket_id": made["ticket_id"],
                    "next": f"Say the status line, then that you've logged it for the team, reference {made['ticket_id']}."}
        return {**result, "next": "Say the status line, then: " + made.get("hint", "offer a specialist.")}
    category = "compliance" if result["status"] == "under review" else "payment"
    made = cases.create_escalation(repo, cid, category, reason, now, reference=ref)
    if "escalation_id" in made:
        return {**result, "escalation_id": made["escalation_id"], "ticket_id": made["ticket_id"],
                "next": "Say the status line, then that you've passed it to a specialist, then ask whether they'd "
                        "like a call back or an email."}
    if made.get("error") == "needs_contact":
        return {**result, "next": "Say the status line, then that a specialist needs to look into it, and ask for "
                                  f"their name and email. Then call create_escalation with them and reference {ref}."}
    return {**result, "next": "Say the status line, then: " + made.get("hint", "offer a specialist.")}


def lookup_transaction(repo: Any, cid: str, transaction_id: str | None, today: date,
                       now: datetime | None = None) -> dict[str, Any]:
    ref = parse_reference(transaction_id, default_prefix="TXN")
    if ref is None:
        return _malformed(repo, cid, transaction_id)
    if ref.startswith("PAY-"):
        return lookup_payout(repo, cid, payout_id=ref, transaction_id=None, today=today, now=now)
    record, problem = _lookup(repo, cid, "transaction", ref)
    if problem:
        return problem
    if record is None:
        return _not_found(ref)
    return _act_on(repo, cid, _status_result("transaction", ref, record, "estimated_arrival", today), now)


def lookup_payout(repo: Any, cid: str, payout_id: str | None, transaction_id: str | None, today: date,
                  now: datetime | None = None) -> dict[str, Any]:
    pay_ref = parse_reference(payout_id, default_prefix="PAY") if payout_id else None
    txn_ref = parse_reference(transaction_id, default_prefix="TXN") if transaction_id else None
    if pay_ref and pay_ref.startswith("TXN-"):  # a transaction reference given as the payout
        pay_ref, txn_ref = None, pay_ref
    if not pay_ref and not txn_ref:
        return _malformed(repo, cid, payout_id or transaction_id)
    record, problem = (_lookup(repo, cid, "payout", pay_ref) if pay_ref
                       else _lookup(repo, cid, "payout_by_transaction", txn_ref))
    if problem:
        return problem
    if record is None:
        return _not_found(pay_ref or txn_ref)
    return _act_on(repo, cid, _status_result("payout", record["payout_id"], record, "scheduled_for", today), now)
