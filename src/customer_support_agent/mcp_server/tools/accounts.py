"""lookup_customer, lookup_transaction, lookup_payout (SPECS §3, §5, §9).

Identity always comes from the conversation record, never from the model. Lookups return only
what the caller may hear: no amounts, no other customers, no failure reasons.
"""

import hashlib
from datetime import date
from typing import Any

from customer_support_agent.domain.normalise import normalise_company, normalise_email, parse_reference
from customer_support_agent.domain.status import caller_status
from customer_support_agent.mcp_server.tools.common import MAX_LOOKUP_MISSES, MAX_VERIFICATION_ATTEMPTS, error

LOOKUP_CUSTOMER = (
    "Verify the caller and get their account summary. Needs BOTH the email and the company name. Leave out "
    "either one to use what the caller typed in the pre-call form. Returns found=false on any mismatch (never say which "
    "part failed). Max 2 attempts per call, then escalate as 'identity not verified'."
)
LOOKUP_TRANSACTION = (
    "Status of one transaction, from the reference the caller gives (pass exactly what they said). "
    "Returns only a status, a line you can say, and next_step (none / ticket / escalate). Never guess a reference."
)
LOOKUP_PAYOUT = (
    "Status of one payout, by its payout reference or its transaction reference. Returns only a status, "
    "a line you can say, and next_step. Never state a failure reason."
)


def _verified_summary(c: dict) -> dict[str, Any]:
    return {"found": True, "customer_id": c["customer_id"], "company_name": c["company_name"], "plan": c["plan"],
            "account_status": c["account_status"], "kyc_status": c["kyc_status"],
            "support_notes": c["support_notes"]}  # for deciding only: the prompt forbids saying it


def lookup_customer(repo: Any, cid: str, email: str | None, company_name: str | None) -> dict[str, Any]:
    conversation = repo.ensure_conversation(cid) or {}
    if conversation.get("verified_customer_id"):  # already verified this call: no new attempt
        return _verified_summary(repo.customer(conversation["verified_customer_id"]))
    if (conversation.get("verification_attempts") or 0) >= MAX_VERIFICATION_ATTEMPTS:
        return error("limit_reached", "Too many attempts. Don't try again: escalate as 'identity not verified'.")

    email = email or conversation.get("caller_email")  # what was said wins; otherwise the pre-call form
    company_name = company_name or conversation.get("caller_company")
    wanted_email, wanted_company = normalise_email(email), normalise_company(company_name)
    if not wanted_email or not wanted_company:
        return error("invalid_input", "Need both a valid email and the company name. Ask for whichever is missing.")

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
                "hint": "Ask them to repeat the email and company once." if left > 0
                else "Don't try again: escalate as 'identity not verified'."}
    repo.mark_verified(cid, customer["customer_id"])
    return _verified_summary(customer)


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


def lookup_transaction(repo: Any, cid: str, transaction_id: str | None, today: date) -> dict[str, Any]:
    ref = parse_reference(transaction_id, default_prefix="TXN")
    if ref is None:
        return _malformed(repo, cid, transaction_id)
    if ref.startswith("PAY-"):
        return lookup_payout(repo, cid, payout_id=ref, transaction_id=None, today=today)
    record, problem = _lookup(repo, cid, "transaction", ref)
    if problem:
        return problem
    if record is None:
        return _not_found(ref)
    return _status_result("transaction", ref, record, "estimated_arrival", today)


def lookup_payout(repo: Any, cid: str, payout_id: str | None, transaction_id: str | None, today: date) -> dict[str, Any]:
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
    return _status_result("payout", record["payout_id"], record, "scheduled_for", today)
