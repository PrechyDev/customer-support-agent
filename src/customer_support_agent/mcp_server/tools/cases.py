"""create_support_ticket, create_escalation, log_conversation_event (SPECS §6, §9).

A ticket records the problem, an escalation records the person. Every escalation has a linked
ticket (created here if needed), and writes an escalation_created event. Repeats return the
existing record, so retries never duplicate. Contact details come from the verified customer's
record or the pre-call form before the model's words.
"""

from datetime import datetime
from typing import Any

from customer_support_agent.domain.callbacks import CallbackError, callback_window
from customer_support_agent.domain.normalise import mask_email, normalise_email, parse_reference
from customer_support_agent.mcp_server.tools.common import (
    MAX_ESCALATIONS, MAX_TICKETS, PRIORITIES, TICKET_CATEGORIES, error,
)

EVENT_TYPES = ("sensitive_request", "injection_attempt", "verification_failed", "caller_frustrated", "other")

CREATE_TICKET = (
    "Log a problem for the support team (e.g. a failed transaction with a reference). category: compliance, "
    "account, dispute, payment or other. priority: high (money stuck or failed), medium, low. Needs a verified "
    "caller or a valid reference; otherwise use create_escalation. Repeats return the same ticket."
)
CREATE_ESCALATION = (
    "Hand the caller to a specialist: restrictions, compliance, disputes/refunds/cancellations, frustration, "
    "next_step=escalate, failed verification, or they want a human. Links a ticket automatically. Contact comes "
    "from the verified account or the pre-call form; only pass user_name/user_email if neither exists. For a "
    "callback, pass callback_place (city or time zone), callback_day and callback_time (morning/afternoon/evening/"
    "'3pm'/'any'); call it again with these to add a time to an existing escalation. Say the follow_up_summary."
)
LOG_EVENT = (
    "Record a judgement call: sensitive_request, injection_attempt, verification_failed, caller_frustrated or "
    "other. Not for routine steps (those are logged automatically)."
)


def _ticket_customer(repo: Any, conversation: dict, reference: str) -> str | None:
    if conversation.get("verified_customer_id"):
        return conversation["verified_customer_id"]
    if reference.startswith("TXN-"):
        record = repo.transaction(reference)
    elif reference.startswith("PAY-"):
        record = repo.payout(reference)
    else:
        record = None
    return record["customer_id"] if record else None


def create_support_ticket(repo: Any, cid: str, category: str, priority: str, summary: str,
                          reference: str | None = None) -> dict[str, Any]:
    if category not in TICKET_CATEGORIES:
        return error("invalid_input", f"category must be one of: {', '.join(TICKET_CATEGORIES)}.")
    if priority not in PRIORITIES:
        return error("invalid_input", f"priority must be one of: {', '.join(PRIORITIES)}.")
    if not (summary or "").strip():
        return error("invalid_input", "Give a one-sentence summary of the problem.")
    ref = parse_reference(reference) if reference else ""
    if reference and not ref:
        return error("invalid_input", "That reference isn't clear. Ask them to repeat it once.")

    conversation = repo.ensure_conversation(cid) or {}
    tickets = repo.tickets(cid)
    existing = next((t for t in tickets if (t["category"], t["reference"]) == (category, ref)), None)
    if existing:
        return {"ticket_id": existing["ticket_id"], "status": existing["status"], "created": False}
    customer_id = _ticket_customer(repo, conversation, ref)
    if customer_id is None:
        return error("needs_contact", "Nobody could follow up on this: use create_escalation with the caller's "
                                      "name and email instead (it creates the ticket too).")
    if len(tickets) >= MAX_TICKETS:
        return error("limit_reached", "No more tickets on this call. Tell the caller you've logged what you can on "
                                      "this call, and for anything else to use their RelayPay dashboard or call again.")
    ticket_id, created = repo.create_ticket(cid, customer_id, category, priority, summary.strip()[:500], ref)
    return {"ticket_id": ticket_id, "status": "open", "created": created}


def _contact(repo: Any, conversation: dict, user_name: str | None, user_email: str | None) -> tuple[str | None, str | None]:
    """The verified account first, then the pre-call form, then what the caller said."""
    if conversation.get("verified_customer_id"):
        c = repo.customer(conversation["verified_customer_id"])
        return c["contact_name"], c["contact_email"]
    name = conversation.get("caller_name") or (user_name or "").strip() or None
    email = conversation.get("caller_email") or normalise_email(user_email)
    return name, email


def _callback(place: str | None, day: str | None, when: str | None, now: datetime) -> dict[str, Any]:
    window = callback_window(place, day or "", when or "", now)
    raw = " ".join(p for p in (day, when, place) if p)
    if window is None:
        return {"call_booked": False, "preferred_time_raw": raw or "any time", "callback_timezone": None,
                "callback_start_utc": None, "callback_end_utc": None, "_spoken": None}
    return {"call_booked": True, "preferred_time_raw": raw, "callback_timezone": window.timezone,
            "callback_start_utc": window.start_utc, "callback_end_utc": window.end_utc, "_spoken": window.spoken}


def _follow_up(spoken: str | None) -> str:
    return ("A specialist will follow up with you by email" +
            (f", and will aim to call you {spoken}." if spoken else "."))


def create_escalation(repo: Any, cid: str, category: str, reason: str, now: datetime,
                      user_name: str | None = None, user_email: str | None = None,
                      callback_place: str | None = None, callback_day: str | None = None,
                      callback_time: str | None = None, preferred_time: str | None = None,
                      ticket_id: str | None = None) -> dict[str, Any]:
    if category not in TICKET_CATEGORIES:
        return error("invalid_input", f"category must be one of: {', '.join(TICKET_CATEGORIES)}.")
    if not (reason or "").strip():
        return error("invalid_input", "Give a one-sentence reason for the escalation.")

    callback = None
    if callback_time or callback_day:
        if not callback_place:
            return error("invalid_input", "Ask which city or time zone they're in, then call again.")
        try:
            callback = _callback(callback_place, callback_day, callback_time, now)
        except CallbackError as exc:
            return error(exc.code, exc.hint)
        if preferred_time:
            callback["preferred_time_raw"] = preferred_time.strip()[:200]

    conversation = repo.ensure_conversation(cid) or {}
    escalations = repo.escalations(cid)
    existing = next((e for e in escalations if e["category"] == category), None)
    if existing:  # a repeat, or adding a callback time to it
        spoken = None
        if callback:
            spoken = callback.pop("_spoken")
            repo.set_callback(existing["escalation_id"], callback)
        return {"escalation_id": existing["escalation_id"], "ticket_id": existing["ticket_id"], "status": existing["status"],
                "created": False, "follow_up_summary": _follow_up(spoken)}

    name, email = _contact(repo, conversation, user_name, user_email)
    if not name or not email:
        return error("invalid_input", "Need the caller's name and a valid email. Ask for what's missing, and read the email back.")
    if len(escalations) >= MAX_ESCALATIONS:
        return error("limit_reached", "No more escalations on this call. Tell the caller the specialists already "
                                      "following up have this call's details, and for anything new to use their "
                                      "RelayPay dashboard or call again.")

    verified = bool(conversation.get("verified_customer_id"))
    customer_id = conversation.get("verified_customer_id")
    linked = next((t for t in repo.tickets(cid) if t["ticket_id"] == ticket_id), None) if ticket_id else None
    if linked is None:  # every escalation has a ticket: link this call's own, or create one
        ticket, _ = repo.create_ticket(cid, customer_id, category, "high", reason.strip()[:500], "")
    else:
        ticket = linked["ticket_id"]

    spoken = callback.pop("_spoken") if callback else None
    values = {"conversation_id": cid, "ticket_id": ticket, "customer_id": customer_id, "user_name": name[:100],
              "user_email": email, "category": category, "reason": reason.strip()[:500], "verified": verified,
              **(callback or {"call_booked": False, "preferred_time_raw": (preferred_time or "").strip() or None})}
    escalation_id, created = repo.create_escalation(  # the escalation_created event is written with it
        values, f"{category}: {reason.strip()[:200]}",
        {"ticket_id": ticket, "verified": verified, "contact": mask_email(email)})
    return {"escalation_id": escalation_id, "ticket_id": ticket, "status": "open", "created": created,
            "follow_up_summary": _follow_up(spoken)}


def log_conversation_event(repo: Any, cid: str, event_type: str, summary: str,
                           metadata: dict | None = None) -> dict[str, Any]:
    if event_type not in EVENT_TYPES:
        return error("invalid_input", f"event_type must be one of: {', '.join(EVENT_TYPES)}.")
    if not (summary or "").strip():
        return error("invalid_input", "Give a short summary.")
    # No ensure_conversation: events have no foreign key, and the backend creates the call's row at call start.
    repo.log_event(cid, event_type, summary.strip()[:500], metadata if isinstance(metadata, dict) else {})
    return {"logged": True}
