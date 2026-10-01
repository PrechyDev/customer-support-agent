"""Turns database rows into what the console screens show (docs/CONSOLE_API.md). No SQL, no HTTP: easy to test."""

import ast
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from customer_support_agent.domain.callbacks import CallbackError, spoken_window

OUTCOMES = ("answered", "handed_to_specialist", "ticket_created", "could_not_answer", "caller_hung_up")


def iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


def outcome(row: dict) -> str:
    if row.get("has_escalation"):
        return "handed_to_specialist"
    if row.get("has_ticket"):
        return "ticket_created"
    if row.get("final_status") == "abandoned":
        return "caller_hung_up"
    if row.get("has_decline"):
        return "could_not_answer"
    return "answered"


def duration_s(row: dict) -> int | None:
    start, end = row.get("started_at"), row.get("ended_at")
    return int((end - start).total_seconds()) if start and end else None


def conversation_row(row: dict) -> dict:
    return {"conversation_id": row["conversation_id"],
            "caller": row.get("company_name") or row.get("caller_name") or "Unknown caller",
            "started_at": iso(row["started_at"]), "duration_s": duration_s(row), "outcome": outcome(row),
            "summary": row.get("summary"), "rating": row.get("rating"), "channel": row.get("channel") or "voice"}


def callback(row: dict) -> dict | None:
    if not (row.get("call_booked") and row.get("callback_start_utc") and row.get("callback_timezone")):
        return None
    try:
        spoken = spoken_window(row["callback_start_utc"], row["callback_end_utc"], row["callback_timezone"])
    except CallbackError:
        spoken = None
    return {"spoken": spoken, "start_utc": iso(row["callback_start_utc"])}


def case_row(row: dict) -> dict:
    return {"case_id": row["case_id"], "case_type": row["case_type"], "title": row["title"],
            "category": row["category"], "priority": row["priority"], "status": row["status"],
            "owner": {"member_id": row["owner_id"], "name": row["owner_name"]} if row.get("owner_id") else None,
            "customer_id": row.get("customer_id"), "company": row.get("company"),
            "reference": row.get("reference") or None, "callback": callback(row),
            "contact_method": row.get("contact_method"), "created_at": iso(row["created_at"]),
            "resolved_at": iso(row.get("resolved_at")), "conversation_id": row.get("conversation_id"),
            "ticket_id": row.get("ticket_id")}  # an escalation's linked ticket; a ticket's own ID


def member_view(row: dict) -> dict:
    return {"member_id": row["member_id"], "email": row["email"], "name": row.get("name"), "role": row["role"],
            "status": row["status"], "created_at": iso(row.get("created_at")),
            "activated_at": iso(row.get("activated_at")), "last_login_at": iso(row.get("last_login_at")),
            "invited_by_name": row.get("invited_by_name")}


def _result(text: str | None) -> dict:
    """tool_calls.result_summary is a Python-dict string (capped at 300 chars); read it safely, or give up."""
    try:
        value = ast.literal_eval(text or "")
        return value if isinstance(value, dict) else {}
    except (ValueError, SyntaxError):
        return {}


def action(row: dict) -> dict:
    """A tool call as a plain-language step ("Checked transaction TXN-9001")."""
    name, ok = row["tool_name"], row["status"] == "ok"
    result = _result(row.get("result_summary"))
    ref = result.get("reference") or ""
    labels = {
        "lookup_transaction": f"Checked transaction {ref}".strip(),
        "lookup_payout": f"Checked payout {ref}".strip(),
        "lookup_customer": "Found the account" if result.get("found") else "Tried to verify the caller",
        "create_support_ticket": f"Opened ticket {result.get('ticket_id', '')}".strip(),
        "create_escalation": f"Handed to a specialist {result.get('escalation_id', '')}".strip(),
        "log_conversation_event": "Recorded an event",
    }
    label = labels.get(name, name.replace("_", " ").capitalize())
    detail = result.get("say") or result.get("status") or result.get("error") or ""
    if result.get("escalation_id") and name.startswith("lookup"):
        detail = f"{detail} Passed to a specialist ({result['escalation_id']})".strip()
    return {"when": iso(row["created_at"]), "label": label, "detail": detail, "ok": ok and "error" not in result}


def transcript(turns: list[dict]) -> list[dict]:
    out = []
    for turn in turns:
        if turn.get("user_transcript"):
            out.append({"when": iso(turn["created_at"]), "speaker": "caller", "text": turn["user_transcript"],
                        "answer_type": None, "note": None})
        if turn.get("assistant_response"):
            out.append({"when": iso(turn["created_at"]), "speaker": "assistant", "text": turn["assistant_response"],
                        "answer_type": turn.get("answer_type"), "note": turn.get("confidence_note")})
    return out


def _pct(part: int, whole: int) -> int | None:
    return round(100 * part / whole) if whole else None


def analytics(rows: list[dict], previous_count: int, declined: list[dict], start: date, end: date) -> dict:
    """rows: the conversations started in [start, end]; previous_count: the equal-length period before it."""
    outcomes = Counter(outcome(r) for r in rows)
    rated = [r for r in rows if r.get("rating")]
    durations = [d for d in (duration_s(r) for r in rows) if d is not None]
    days = (end - start).days + 1
    bucket = "day" if days <= 31 else "week" if days <= 120 else "month"
    counts: Counter = Counter()
    for r in rows:
        day = r["started_at"].astimezone(UTC).date()
        key = day if bucket == "day" else day - timedelta(days=day.weekday()) if bucket == "week" else day.replace(day=1)
        counts[key] += 1
    points, cursor = [], start
    while cursor <= end:
        key = cursor if bucket == "day" else cursor - timedelta(days=cursor.weekday()) if bucket == "week" \
            else cursor.replace(day=1)
        if not points or points[-1]["start"] != key.isoformat():
            points.append({"start": key.isoformat(), "count": counts.get(key, 0)})
        cursor += timedelta(days=1)
    questions = Counter(" ".join(re.sub(r"[^\w\s'?]", " ", q["user_transcript"]).split()).capitalize()
                        for q in declined if q.get("user_transcript"))
    total = len(rows)
    return {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "kpis": {"conversations": total,
                 "conversations_change_pct": round(100 * (total - previous_count) / previous_count)
                 if previous_count else None,
                 "answered_by_assistant_pct": _pct(outcomes["answered"], total),
                 "handed_to_specialist_pct": _pct(outcomes["handed_to_specialist"], total),
                 "rated_helpful_pct": _pct(sum(r["rating"] == "yes" for r in rated), len(rated)),
                 "average_duration_s": round(sum(durations) / len(durations)) if durations else None},
        "series": {"bucket": bucket, "points": points},
        "ended": {name: outcomes.get(name, 0) for name in OUTCOMES},
        "unanswered": [{"question": q, "times": n} for q, n in questions.most_common(10)],
    }
