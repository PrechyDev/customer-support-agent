"""create_support_ticket, create_escalation, log_conversation_event (SPECS §6, §9).

A ticket records the problem, an escalation records the person. Every escalation has a linked
ticket (created here if needed), and writes an escalation_created event. Repeats return the
existing record, so retries never duplicate. Contact details come from the verified customer's
record or the pre-call form before the model's words.
"""

from datetime import datetime
from typing import Any

from customer_support_agent.domain.callbacks import CallbackError, callback_window, calling_code, resolve_timezone
from customer_support_agent.domain.normalise import (
    mask_email,
    normalise_email,
    normalise_phone,
    spoken_email,
    parse_reference,
    spoken_phone,
)
from customer_support_agent.agent.spoken import heard_digits, heard_text
from customer_support_agent.mcp_server.tools.common import (
    MAX_ESCALATIONS, MAX_TICKETS, PRIORITIES, TICKET_CATEGORIES, confirmed, error,
)

EVENT_TYPES = ("sensitive_request", "injection_attempt", "verification_failed", "caller_frustrated", "other")

CREATE_TICKET = (
    "Log a problem for the support team (e.g. a failed transaction with a reference). category: compliance, "
    "account, dispute, payment or other. priority: high (money stuck or failed), medium, low. Needs a verified "
    "caller or a valid reference; otherwise use create_escalation. Repeats return the same ticket."
)
CREATE_ESCALATION = (
    "Hand the caller to a specialist: restrictions, compliance, disputes/refunds/cancellations, frustration, "
    "next_step=escalate, failed verification, or they want a human. category: compliance, account, dispute, "
    "payment or other. Pass the transaction or payout reference if there is one. Links a ticket automatically. "
    "No verification needed. Call it straight away: contact comes from the verified account or the pre-call form, "
    "and it returns needs_contact only if neither exists; then ask for the caller's name and email and pass "
    "user_name/user_email (it returns confirm_email: say its 'say' line, then call again with email_confirmed true). "
    "Then ask how they'd like to be contacted; for email, call it again with contact_method='email'. For a call: "
    "pass contact_method='call', callback_day, callback_time (morning/afternoon/evening/'3pm'/'any'), "
    "callback_place (city or time zone) and callback_phone (exactly as said; a local number is fine when the place "
    "is known; not needed if the form has one). It checks the time and returns confirm_phone: say its 'say' line "
    "once, then call again with phone_confirmed true. Never read numbers or emails back yourself. Say the "
    "follow_up_summary."
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
                          reference: str | None = None, now: datetime | None = None) -> dict[str, Any]:
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
    if customer_id is None and now is not None and conversation.get("caller_name") and conversation.get("caller_email"):
        # Nobody on file to follow up a ticket, but the pre-call form says who to contact: escalate in code
        # (an eval caught Bex asking for a name the form already had, after needs_contact).
        made = create_escalation(repo, cid, category, summary, now, reference=reference)
        if "escalation_id" in made:
            return {**made, "next": "Say you've passed it to a specialist, then ask whether they'd like a call back "
                                    "or an email. Don't ask for their name or email: the form has them."}
        return made
    if customer_id is None:
        return error("needs_contact", "Nobody could follow up on this: use create_escalation with the caller's "
                                      "name and email instead (it creates the ticket too).")
    if len(tickets) >= MAX_TICKETS:
        return error("limit_reached", "No more tickets on this call. Tell the caller you've logged what you can on "
                                      "this call, and for anything else to use their RelayPay dashboard or call again.")
    ticket_id, created = repo.create_ticket(cid, customer_id, category, priority, summary.strip()[:500], ref,
                                            caller_verified=bool(conversation.get("verified_customer_id")))
    return {"ticket_id": ticket_id, "status": "open", "created": created}


def _contact(repo: Any, conversation: dict, user_name: str | None, user_email: str | None) -> tuple[str | None, str | None]:
    """The verified account first, then the pre-call form, then what the caller said."""
    if conversation.get("verified_customer_id"):
        c = repo.customer(conversation["verified_customer_id"])
        return c["contact_name"], c["contact_email"]
    name = conversation.get("caller_name") or (user_name or "").strip() or None
    email = conversation.get("caller_email") or normalise_email(user_email)
    return name, email


_ANY_TIME = ("", "any", "anytime", "any time")


def _call_request(cid: str, conversation: dict, place: str | None, day: str | None, when: str | None,
                  phone: str | None, phone_confirmed: bool, preferred_time: str | None, now: datetime) -> tuple[dict | None, dict | None]:
    """(callback columns, error). The time and place are checked first (a weekend or an unknown place is
    caught before anything is confirmed). The place also gives the country code, so a local number
    ('0814 346 3800') is fine. A spoken number is confirmed once, together with the time."""
    raw = (preferred_time or " ".join(p for p in (day, when, place) if p) or "any time").strip()[:200]
    values = {"contact_method": "call", "preferred_time_raw": raw, "call_booked": False,
              "callback_timezone": None, "callback_start_utc": None, "callback_end_utc": None}
    window, zone = None, None
    any_time = (when or "").strip().lower() in _ANY_TIME and not day
    try:
        if place:
            zone = resolve_timezone(place).key
        if not any_time:
            if not place:
                return None, error("invalid_input", "Ask which city or time zone they're in, then call again.")
            window = callback_window(place, day or "", when or "", now)
    except CallbackError as exc:
        return None, error(exc.code, exc.hint)
    if window is not None:
        values.update(call_booked=True, callback_timezone=window.timezone, callback_start_utc=window.start_utc,
                      callback_end_utc=window.end_utc)
    spoken = window.spoken if window else None

    number = conversation.get("caller_phone")  # typed in the form: no read-back needed
    if phone:
        number = normalise_phone(phone, default_code=calling_code(zone))
        if number is None:
            return None, error("invalid_input", "Ask for the number with the country code (we don't know which "
                                                "country it's in), then call again.")
        local = spoken_phone(number).replace(" ", "")  # e.g. 08143463800, as the caller would say it
        heard = any(heard_digits(cid, digits) for digits in (local, number[1:]))
        if not confirmed(cid, "phone", number, phone_confirmed, heard):
            when_said = f", on {spoken}" if spoken else ""
            return None, {"error": "confirm_phone", "say": f"Just to confirm: {spoken_phone(number)}{when_said}. Is that right?",
                          "hint": "Read the say line once; if they confirm, call again with phone_confirmed true."}
    if not number:
        when_ok = f"The time works ({spoken}). " if spoken else "The time works. "
        return None, error("needs_phone", when_ok + "Now ask for the best number to reach them.")
    return {**values, "callback_phone": number, "_spoken": spoken}, None


def _follow_up(method: str, spoken: str | None) -> str:
    if method == "call" and spoken:
        return f"Lovely, a specialist will call you on {spoken}."
    if method == "call":
        return "Lovely, a specialist will call you as soon as one is free."
    return "Lovely, a specialist will email you."


def create_escalation(repo: Any, cid: str, category: str, reason: str, now: datetime,
                      user_name: str | None = None, user_email: str | None = None, reference: str | None = None,
                      contact_method: str | None = None, callback_place: str | None = None,
                      callback_day: str | None = None, callback_time: str | None = None,
                      callback_phone: str | None = None, preferred_time: str | None = None,
                      ticket_id: str | None = None, email_confirmed: bool = False,
                      phone_confirmed: bool = False) -> dict[str, Any]:
    if category not in TICKET_CATEGORIES:
        return error("invalid_input", f"category must be one of: {', '.join(TICKET_CATEGORIES)}.")
    if not (reason or "").strip():
        return error("invalid_input", "Give a one-sentence reason for the escalation.")
    if contact_method not in (None, "email", "call"):
        return error("invalid_input", "contact_method must be email or call.")
    ref = parse_reference(reference) if reference else ""
    if reference and not ref:
        return error("invalid_input", "That reference isn't clear. Ask them to repeat it once.")

    conversation = repo.ensure_conversation(cid) or {}
    wants_call = contact_method == "call" or bool(callback_day or callback_time or callback_phone)
    callback = None
    if wants_call:
        callback, problem = _call_request(cid, conversation, callback_place, callback_day, callback_time, callback_phone,
                                          phone_confirmed, preferred_time, now)
        if problem:
            return problem
    method = "call" if wants_call else "email"
    spoken = callback.pop("_spoken") if callback else None

    escalations = repo.escalations(cid)
    existing = next((e for e in escalations if e["category"] == category), None)
    if existing is None and ref and escalations:
        # The same payment under another category is the same case (found in an eval: a lookup escalated
        # PAY-7002 as compliance, then the model added the contact choice as "payment" and made a second case).
        same_ref = {t["ticket_id"] for t in repo.tickets(cid) if t.get("reference") == ref}
        existing = next((e for e in escalations if e["ticket_id"] in same_ref), None)
    if existing:  # a repeat, or adding how they'd like to be contacted
        if callback:
            repo.set_callback(existing["escalation_id"], callback)
        elif contact_method == "email" and existing.get("contact_method") == "call":
            repo.set_callback(existing["escalation_id"], {"contact_method": "email"})
        current = method if (callback or contact_method) else existing.get("contact_method", "email")
        return {"escalation_id": existing["escalation_id"], "ticket_id": existing["ticket_id"],
                "status": existing["status"], "created": False, "follow_up_summary": _follow_up(current, spoken)}

    name, email = _contact(repo, conversation, user_name, user_email)
    if not name or not email:
        return error("needs_contact", "Ask for the caller's name and email, then call again with user_name and "
                                      "user_email.")
    email_was_spoken = not (conversation.get("verified_customer_id") or conversation.get("caller_email"))
    heard = heard_text(cid, spoken_email(email))  # only the spelled read-back counts (see spoken_email)
    if email_was_spoken and not confirmed(cid, "email", email, email_confirmed, heard):  # misheard = nobody follows up
        return {"error": "confirm_email", "say": f"Just to confirm, that's {spoken_email(email)}. Is that right?",
                "hint": "Read the email back; if they confirm, call again with email_confirmed true."}
    if len(escalations) >= MAX_ESCALATIONS:
        return error("limit_reached", "No more escalations on this call. Tell the caller the specialists already "
                                      "following up have this call's details, and for anything new to use their "
                                      "RelayPay dashboard or call again.")

    verified = bool(conversation.get("verified_customer_id"))
    customer_id = conversation.get("verified_customer_id")
    linked = next((t for t in repo.tickets(cid) if t["ticket_id"] == ticket_id), None) if ticket_id else None
    if linked is None:  # every escalation has a ticket: link this call's own, or create one (same key = same ticket)
        ticket, _ = repo.create_ticket(cid, customer_id or _ticket_customer(repo, conversation, ref), category, "high",
                                       reason.strip()[:500], ref, caller_verified=verified)
    else:
        ticket = linked["ticket_id"]

    values = {"conversation_id": cid, "ticket_id": ticket, "customer_id": customer_id, "user_name": name[:100],
              "user_email": email, "category": category, "reason": reason.strip()[:500], "verified": verified,
              **(callback or {"contact_method": "email", "call_booked": False,
                              "preferred_time_raw": (preferred_time or "").strip()[:200] or None})}
    escalation_id, created = repo.create_escalation(  # the escalation_created event is written with it
        values, f"{category}: {reason.strip()[:200]}",
        {"ticket_id": ticket, "verified": verified, "contact": mask_email(email), "method": method})
    asked_how = method == "email" and contact_method is None  # first step: ask how they'd like to be contacted
    result = {"escalation_id": escalation_id, "ticket_id": ticket, "status": "open", "created": created,
              "follow_up_summary": "I've passed this to a specialist." if asked_how else _follow_up(method, spoken)}
    if asked_how:
        result["next"] = "Ask whether they'd like a call back or to be reached by email."
    return result


def log_conversation_event(repo: Any, cid: str, event_type: str, summary: str,
                           metadata: dict | None = None) -> dict[str, Any]:
    if event_type not in EVENT_TYPES:
        return error("invalid_input", f"event_type must be one of: {', '.join(EVENT_TYPES)}.")
    if not (summary or "").strip():
        return error("invalid_input", "Give a short summary.")
    # No ensure_conversation: events have no foreign key, and the backend creates the call's row at call start.
    repo.log_event(cid, event_type, summary.strip()[:500], metadata if isinstance(metadata, dict) else {})
    return {"logged": True}
