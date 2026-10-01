"""The support console's API (docs/CONSOLE_API.md): sign-in, invites, team, cases, conversations, customers,
analytics. Every rule is enforced here, whatever the screens show.

Security: sessions are signed HttpOnly SameSite=Strict cookies; every POST/PATCH needs the
X-Requested-With: relaypay-console header (CSRF guard); logins and invite links are rate limited; failed
sign-ins never say which part was wrong; invite links are single use, expire in 72 h and are stored hashed.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from customer_support_agent.api.ratelimit import RateLimiter, client_ip
from customer_support_agent.config import ConsoleSettings
from customer_support_agent.console import permissions as perms
from customer_support_agent.console import security, views
from customer_support_agent.db.console_store import CASE_TABLES, ConsoleStore
from customer_support_agent.db.repository import RepositoryUnavailable
from customer_support_agent.domain.status import caller_status

logger = logging.getLogger(__name__)

COOKIE = "rp_console"
CSRF_HEADER, CSRF_VALUE = "x-requested-with", "relaypay-console"
CONSOLE_PAGE = Path(__file__).resolve().parent.parent / "web" / "static" / "console" / "index.html"
NOTE_MAX, RESOLVE_MAX, MAX_RANGE_DAYS = 1000, 500, 366


class ConsoleError(Exception):
    def __init__(self, status: int, code: str, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.status, self.body = status, {"error": code, "detail": detail, **extra}


def _fail(status: int, code: str, detail: str, **extra: Any) -> None:
    raise ConsoleError(status, code, detail, **extra)


def console_router(store: ConsoleStore | None, settings: ConsoleSettings,
                   now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> APIRouter:
    router = APIRouter(prefix="/console/api")
    login_by_account = RateLimiter(limit=5, window_seconds=15 * 60)  # per address + email
    login_by_address = RateLimiter(limit=20, window_seconds=15 * 60)
    link_tries = RateLimiter(limit=20, window_seconds=15 * 60)

    async def db(fn: Callable, *args: Any, **kwargs: Any) -> Any:
        if store is None or not settings.session_secret:
            _fail(503, "console_unavailable", "The console isn't set up yet.")
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except RepositoryUnavailable:
            logger.warning("Console request failed: database unavailable")
            _fail(503, "database_unavailable", "The database can't be reached right now. Please try again.")

    def csrf(request: Request) -> None:
        if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            _fail(403, "csrf", "Missing request header.")

    async def body(request: Request) -> dict:
        csrf(request)
        try:
            data = await request.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            _fail(400, "invalid_input", "Send a JSON object.")
        return data

    async def signed_in(request: Request) -> dict:
        found = security.read_session(settings.session_secret or "", request.cookies.get(COOKIE))
        if not found:
            _fail(401, "signed_out", "Please sign in.")
        member = await db(store.member, found[0])
        if not member or member["status"] != "active" or member["session_version"] != found[1]:
            _fail(401, "signed_out", "Please sign in.")
        return member

    async def admin(request: Request) -> dict:
        member = await signed_in(request)
        if not perms.is_admin(member["role"]):
            _fail(403, "forbidden", "Only admins can do that.")
        return member

    def start_session(request: Request, response: JSONResponse, member: dict) -> JSONResponse:
        https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        response.set_cookie(COOKIE, security.sign_session(settings.session_secret, member["member_id"],
                                                          member["session_version"]),
                            max_age=security.SESSION_SECONDS, httponly=True, samesite="strict", secure=https,
                            path="/")
        return response

    def link_url(request: Request, token: str) -> str:
        base = settings.public_base_url or str(request.base_url).rstrip("/")
        return f"{base}/console/invite/{token}"

    async def new_link(request: Request, member_id: str | None, kind: str, **create: Any) -> tuple[str, str, str]:
        """(member_id, invite_url, expires_at) for a new or existing member; their old link stops working."""
        token, digest = security.new_link_token()
        expires = now() + timedelta(seconds=security.INVITE_SECONDS)
        if member_id is None:
            member_id = await db(store.create_member, create["email"], create["role"], create["invited_by"],
                                 digest, kind, expires)
            if member_id is None:
                _fail(409, "already_member", "Someone with that email is already on the team.")
        else:
            await db(store.set_link, member_id, digest, kind, expires)
        return member_id, link_url(request, token), views.iso(expires)

    # --- auth ------------------------------------------------------------------------------
    @router.post("/login")
    async def login(request: Request):
        data = await body(request)
        email = security.normalise_email(data.get("email"))
        ip = client_ip(request)
        if login_by_address.blocked(ip) or login_by_account.blocked(f"{ip}|{email}"):
            _fail(429, "too_many_attempts", "Too many sign-in attempts. Please wait 15 minutes and try again.")
        member = await db(store.member_by_email, email) if email else None
        ok = security.verify_password(str(data.get("password") or ""), member["password_hash"] if member else None)
        if not (ok and member and member["status"] == "active"):
            login_by_address.hit(ip), login_by_account.hit(f"{ip}|{email}")
            logger.info("Console sign-in failed (address=%s)", ip)
            _fail(401, "invalid_credentials", "Email or password is incorrect.")
        login_by_account.reset(f"{ip}|{email}")
        await db(store.touch_login, member["member_id"])
        logger.info("Console sign-in (member=%s role=%s)", member["member_id"], member["role"])
        return start_session(request, JSONResponse({"member": views.member_view(member)}), member)

    @router.post("/logout")
    async def logout(request: Request):
        csrf(request)
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/")
        return response

    @router.get("/me")
    async def me(request: Request):
        member = await signed_in(request)
        return {"member": views.member_view(member), "permissions": perms.permissions(member["role"])}

    async def link_member(request: Request, token: str) -> dict:
        if link_tries.hit(client_ip(request)):
            _fail(429, "too_many_attempts", "Too many attempts. Please wait 15 minutes.")
        member = await db(store.member_by_token, security.token_hash(token)) if 20 <= len(token) <= 100 else None
        if not member:
            _fail(410, "invite_invalid", "This link has expired or has already been used. Ask an admin for a new one.")
        return member

    @router.get("/invites/{token}")
    async def invite_info(request: Request, token: str):
        member = await link_member(request, token)
        return {"email": member["email"], "role": member["role"], "kind": member["invite_kind"] or "invite"}

    @router.post("/invites/{token}/accept")
    async def accept_invite(request: Request, token: str):
        data = await body(request)
        member = await link_member(request, token)
        problems = security.check_new_password(data.get("name"), data.get("password"), data.get("confirm_password"),
                                               member["email"])
        if problems:
            _fail(400, "invalid_input", "Please fix the highlighted fields.", fields=problems)
        await db(store.accept_link, member["member_id"], data["name"].strip(), security.hash_password(data["password"]))
        member = await db(store.member, member["member_id"])
        await db(store.touch_login, member["member_id"])
        logger.info("Console account set up (member=%s role=%s)", member["member_id"], member["role"])
        return start_session(request, JSONResponse({"member": views.member_view(member)}), member)

    # --- team ------------------------------------------------------------------------------
    @router.get("/team")
    async def team(request: Request):
        await admin(request)
        return {"members": [views.member_view(m) for m in await db(store.members)]}

    @router.post("/team/invites", status_code=201)
    async def invite(request: Request):
        data = await body(request)
        actor = await admin(request)
        email, role = security.normalise_email(data.get("email")), data.get("role")
        if not email:
            _fail(400, "invalid_input", "Enter a valid email.", fields={"email": "Enter a valid email."})
        if not perms.can_invite(actor["role"], role):
            _fail(403, "forbidden", "You can't invite someone with that role.")
        member_id, url, expires = await new_link(request, None, "invite", email=email, role=role,
                                                 invited_by=actor["member_id"])
        logger.info("Console invite sent (member=%s role=%s by=%s)", member_id, role, actor["member_id"])
        return JSONResponse({"member": views.member_view(await db(store.member, member_id)), "invite_url": url,
                             "expires_at": expires}, status_code=201)

    async def target(actor: dict, member_id: str) -> dict:
        member = await db(store.member, member_id)
        if not member:
            _fail(404, "not_found", "That team member doesn't exist.")
        if member["member_id"] == actor["member_id"]:
            _fail(403, "forbidden", "You can't change your own account here.")
        if not perms.can_manage(actor["role"], member["role"]):
            _fail(403, "forbidden", "You can't manage that team member.")
        return member

    @router.post("/team/{member_id}/resend")
    async def resend(request: Request, member_id: str):
        csrf(request)
        member = await target(await admin(request), member_id)
        if member["status"] != "pending":
            _fail(409, "not_pending", "Only a pending invite can be resent.")
        _, url, expires = await new_link(request, member_id, "invite")
        return {"invite_url": url, "expires_at": expires}

    @router.post("/team/{member_id}/reset-link")
    async def reset_link(request: Request, member_id: str):
        csrf(request)
        member = await target(await admin(request), member_id)
        if member["status"] != "active":
            _fail(409, "not_active", "Only an active member can get a reset link.")
        _, url, expires = await new_link(request, member_id, "reset")
        return {"invite_url": url, "expires_at": expires}

    @router.patch("/team/{member_id}")
    async def update_member(request: Request, member_id: str):
        data = await body(request)
        actor = await admin(request)
        member = await target(actor, member_id)
        if "role" in data:
            if not perms.can_change_role(actor["role"], member["role"], data["role"]):
                _fail(403, "forbidden", "You can't give that role.")
            await db(store.set_role, member_id, data["role"])
        if "status" in data:
            if data["status"] not in ("active", "disabled"):
                _fail(400, "invalid_input", "Status must be active or disabled.")
            status = data["status"] if data["status"] == "disabled" or member["password_hash"] else "pending"
            await db(store.set_status, member_id, status)
        return {"member": views.member_view(await db(store.member, member_id))}

    # --- dashboard -------------------------------------------------------------------------
    @router.get("/summary")
    async def summary(request: Request):
        actor = await signed_in(request)
        today = datetime.combine(now().date(), datetime.min.time(), UTC)
        convs = await db(store.conversations, started_from=today, limit=1000)
        open_cases = await db(store.cases, status="open", limit=500)
        mine = [c for c in open_cases if c["owner_id"] == actor["member_id"]]
        unassigned = [c for c in open_cases if not c["owner_id"]]
        visible = open_cases if perms.is_admin(actor["role"]) else mine + unassigned

        def urgency(case: dict) -> tuple:
            callback_today = case.get("callback_start_utc") and case["callback_start_utc"].date() == now().date()
            return (0 if callback_today else 1 if not case["owner_id"] else 2, case["created_at"])

        answered = sum(views.outcome(c) == "answered" for c in convs)
        recent = await db(store.conversations, limit=5)
        return {"kpis": {"conversations_today": len(convs),
                         "live_now": sum(1 for c in convs if not c["ended_at"]
                                         and c["started_at"] > now() - timedelta(hours=2)),
                         "answered_by_assistant_pct": round(100 * answered / len(convs)) if convs else None,
                         "open_cases": len(open_cases), "assigned_to_me": len(mine), "unassigned": len(unassigned)},
                "needs_attention": [views.case_row(c) for c in sorted(visible, key=urgency)[:5]],
                "recent_conversations": [views.conversation_row(c) for c in recent]}

    # --- cases -----------------------------------------------------------------------------
    @router.get("/cases")
    async def cases(request: Request, type: str = "", filter: str = "open"):
        """One list of cases: escalations and tickets together, unless a type is given."""
        actor = await signed_in(request)
        if (type and type not in CASE_TABLES) or filter not in ("open", "mine", "unassigned", "resolved"):
            _fail(400, "invalid_input", "Unknown case type or filter.")
        rows = await db(store.cases, case_type=type or None, limit=500)
        groups = {"open": [r for r in rows if r["status"] != "closed"],
                  "mine": [r for r in rows if r["status"] != "closed" and r["owner_id"] == actor["member_id"]],
                  "unassigned": [r for r in rows if r["status"] != "closed" and not r["owner_id"]],
                  "resolved": [r for r in rows if r["status"] == "closed"]}
        return {"cases": [views.case_row(r) for r in groups[filter]],
                "counts": {name: len(group) for name, group in groups.items()}}

    async def load_case(case_type: str, case_id: str) -> dict:
        if case_type not in CASE_TABLES:
            _fail(404, "not_found", "That case doesn't exist.")
        case = await db(store.case, case_type, case_id)
        if not case:
            _fail(404, "not_found", "That case doesn't exist.")
        return case

    async def case_detail(case_type: str, case_id: str) -> dict:
        case = await load_case(case_type, case_id)
        extra = await db(store.case_extra, case_type, case_id) or {}
        customer = await db(store.customer, case["customer_id"]) if case.get("customer_id") else None
        related = None
        if case.get("reference"):
            found = await db(store.reference_record, case["reference"])
            if found:
                kind, record = found
                due = record.get("estimated_arrival") if kind == "transaction" else record.get("scheduled_for")
                status = caller_status(kind, record["status"], due, now().date())
                related = {"kind": kind, "reference": case["reference"], "status": record["status"],
                           "line": status.line}
        conversation = await db(store.conversation, case["conversation_id"]) if case.get("conversation_id") else None
        events = await db(store.case_events, case_type, case_id)
        timeline = [{"when": views.iso(case["created_at"]), "who": "Assistant", "kind": "created",
                     "text": f"Created from the call: {extra.get('reason') or case['title']}"}]
        timeline += [{"when": views.iso(e["created_at"]), "who": e["who"] or "System", "kind": e["kind"],
                      "text": e["text"]} for e in events]
        row = views.case_row(case)
        row.update({"reason": extra.get("reason"), "summary": extra.get("summary"),
                    "contact": {"name": extra.get("user_name"), "email": extra.get("user_email"),
                                "phone": extra.get("callback_phone")} if case_type == "escalation" else None,
                    "verified": extra.get("verified"), "preferred_time": extra.get("preferred_time_raw"),
                    "resolution_note": extra.get("resolution_note")})
        return {"case": row,
                "customer": {k: customer[k] for k in ("customer_id", "company_name", "contact_name", "contact_email",
                                                       "plan", "account_status", "kyc_status", "region",
                                                       "support_notes")} if customer else None,
                "related": related,
                "conversation": {"conversation_id": conversation["conversation_id"],
                                 "summary": conversation["summary"], "started_at": views.iso(conversation["started_at"]),
                                 "duration_s": views.duration_s(conversation)} if conversation else None,
                "timeline": timeline}

    @router.get("/cases/{case_type}/{case_id}")
    async def case(request: Request, case_type: str, case_id: str):
        await signed_in(request)
        return await case_detail(case_type, case_id)

    def linked_ticket(case_type: str, case: dict, **fields: Any) -> dict | None:
        """An escalation and its ticket are one case: whatever happens to one happens to the other."""
        if case_type != "escalation" or not case.get("ticket_id"):
            return None
        return {"ticket_id": case["ticket_id"], **fields}

    async def act(case_type: str, case_id: str, actor: dict, kind: str, text: str, ticket: dict | None = None,
                  **update: Any) -> dict:
        """Updates the case (and its linked ticket) and writes the timeline entry. With only_if, a case that
        changed since it was read (someone else got there first) is a 409 and nothing is written."""
        if not await db(store.update_case, case_type, case_id, **update):
            _fail(409, "case_changed", "Someone else just changed this case. Refresh to see it.")
        if ticket:
            await db(store.update_case, "ticket", ticket.pop("ticket_id"), **ticket)
        await db(store.add_case_event, case_type, case_id, actor["member_id"], kind, text)
        logger.info("Case %s %s by member=%s", case_id, kind, actor["member_id"])
        return {"case": (await case_detail(case_type, case_id))["case"]}

    @router.post("/cases/{case_type}/{case_id}/take")
    async def take(request: Request, case_type: str, case_id: str):
        csrf(request)
        actor = await signed_in(request)
        case = await load_case(case_type, case_id)
        if case["owner_id"] or case["status"] == "closed":
            _fail(409, "not_available", "This case already has an owner or is resolved.")
        ticket = linked_ticket(case_type, case, owner_id=actor["member_id"], status="in progress")
        return await act(case_type, case_id, actor, "take", "Took the case.", ticket=ticket,
                         owner_id=actor["member_id"], status="in progress", only_if="unowned_open")

    @router.post("/cases/{case_type}/{case_id}/assign")
    async def assign(request: Request, case_type: str, case_id: str):
        data = await body(request)
        actor = await admin(request)
        case = await load_case(case_type, case_id)
        owner = await db(store.member, str(data.get("member_id") or ""))
        if not owner or owner["status"] != "active":
            _fail(400, "invalid_input", "Choose an active team member.")
        status = "in progress" if case["status"] != "closed" else None
        ticket = linked_ticket(case_type, case, owner_id=owner["member_id"], status=status)
        return await act(case_type, case_id, actor, "assign", f"Assigned to {owner['name'] or owner['email']}.",
                         ticket=ticket, owner_id=owner["member_id"], status=status)

    @router.post("/cases/{case_type}/{case_id}/resolve")
    async def resolve(request: Request, case_type: str, case_id: str):
        data = await body(request)
        actor = await signed_in(request)
        case = await load_case(case_type, case_id)
        if not perms.can_resolve(actor["role"], actor["member_id"], case["owner_id"]):
            _fail(403, "forbidden", "Only the case owner or an admin can resolve it.")
        if case["status"] == "closed":
            _fail(409, "already_resolved", "This case is already resolved.")
        note = str(data.get("note") or "").strip()
        if not 1 <= len(note) <= RESOLVE_MAX:
            _fail(400, "invalid_input", "Add a short note on how it was resolved.",
                  fields={"note": f"1 to {RESOLVE_MAX} characters."})
        ticket = linked_ticket(case_type, case, status="closed", resolution_note=note)
        return await act(case_type, case_id, actor, "resolve", f"Resolved: {note}", ticket=ticket, status="closed",
                         resolution_note=note, only_if="not_closed")

    @router.post("/cases/{case_type}/{case_id}/reopen")
    async def reopen(request: Request, case_type: str, case_id: str):
        csrf(request)
        actor = await admin(request)
        case = await load_case(case_type, case_id)
        if case["status"] != "closed":
            _fail(409, "not_resolved", "Only a resolved case can be reopened.")
        status = "in progress" if case["owner_id"] else "open"
        ticket = linked_ticket(case_type, case, status=status, reopen=True)
        return await act(case_type, case_id, actor, "reopen", "Reopened the case.", ticket=ticket, status=status,
                         reopen=True, only_if="closed")

    @router.post("/cases/{case_type}/{case_id}/notes")
    async def note(request: Request, case_type: str, case_id: str):
        data = await body(request)
        actor = await signed_in(request)
        await load_case(case_type, case_id)
        text = str(data.get("text") or "").strip()
        if not 1 <= len(text) <= NOTE_MAX:
            _fail(400, "invalid_input", "Write a note first.", fields={"text": f"1 to {NOTE_MAX} characters."})
        row = await db(store.add_case_event, case_type, case_id, actor["member_id"], "note", text)
        return {"timeline_entry": {"when": views.iso(row["created_at"]), "who": actor["name"], "kind": "note",
                                   "text": text}}

    # --- conversations, customers ---------------------------------------------------------
    @router.get("/conversations")
    async def conversations(request: Request, search: str = "", outcome: str = "", limit: int = 50):
        await signed_in(request)
        rows = [views.conversation_row(r) for r in await db(store.conversations, search=search.strip()[:100] or None)]
        counts = {"all": len(rows), **{name: sum(r["outcome"] == name for r in rows) for name in views.OUTCOMES}}
        if outcome:
            rows = [r for r in rows if r["outcome"] == outcome]
        return {"conversations": rows[:max(1, min(limit, 100))], "counts": counts}

    @router.get("/conversations/{cid}")
    async def conversation(request: Request, cid: str):
        await signed_in(request)
        row = await db(store.conversation, cid)
        if not row:
            _fail(404, "not_found", "That conversation doesn't exist.")
        detail = views.conversation_row(row)
        detail.update({"verified_customer_id": row["verified_customer_id"],
                       "form": {"name": row["caller_name"], "email": row["caller_email"]}})
        return {"conversation": detail,
                "transcript": views.transcript(await db(store.turns, cid)),
                "actions": [views.action(t) for t in await db(store.tool_calls, cid)],
                "cases": [views.case_row(c) for c in await db(store.cases, conversation_id=cid)],
                "searches": [{"query": s["query"], "chunks": list(s["titles"] or [])} for s in await db(store.searches, cid)]}

    @router.get("/customers")
    async def customers(request: Request, search: str = ""):
        await signed_in(request)
        return {"customers": await db(store.customers, search.strip()[:100] or None)}

    @router.get("/customers/{customer_id}")
    async def customer(request: Request, customer_id: str):
        await signed_in(request)
        row = await db(store.customer, customer_id)
        if not row:
            _fail(404, "not_found", "That customer doesn't exist.")
        txns, payouts = await db(store.customer_money, customer_id)
        return {"customer": {k: v for k, v in row.items()},
                "cases": [views.case_row(c) for c in await db(store.cases, customer_id=customer_id)],
                "conversations": [views.conversation_row(c) for c in await db(store.conversations, customer_id=customer_id)],
                "transactions": [{**t, "created_at": views.iso(t["created_at"]),
                                  "estimated_arrival": views.iso(t["estimated_arrival"]),
                                  "amount": float(t["amount"])} for t in txns],
                "payouts": [{**p, "scheduled_for": views.iso(p["scheduled_for"]), "amount": float(p["amount"])}
                            for p in payouts]}

    # --- analytics, new-item ping ---------------------------------------------------------
    @router.get("/analytics")
    async def analytics(request: Request, start: str = Query("", alias="from"), end: str = Query("", alias="to")):
        await signed_in(request)
        try:
            to_day = date.fromisoformat(end) if end else now().date()
            from_day = date.fromisoformat(start) if start else to_day - timedelta(days=6)
        except ValueError:
            _fail(400, "invalid_input", "Dates must look like 2026-10-01.")
        if from_day > to_day or (to_day - from_day).days >= MAX_RANGE_DAYS:
            _fail(400, "invalid_input", f"Pick a range of up to {MAX_RANGE_DAYS} days.")
        lo = datetime.combine(from_day, datetime.min.time(), UTC)
        hi = datetime.combine(to_day + timedelta(days=1), datetime.min.time(), UTC)
        rows = await db(store.conversations, started_from=lo, started_to=hi, limit=10000)
        previous = await db(store.conversations, started_from=lo - (hi - lo), started_to=lo, limit=10000)
        declined = await db(store.declined_questions, lo, hi)
        return views.analytics(rows, len(previous), declined, from_day, to_day)

    @router.get("/new")
    async def new_items(request: Request, since: str = ""):
        await signed_in(request)
        try:
            after = datetime.fromisoformat(since.replace("Z", "+00:00")) if since else now() - timedelta(minutes=1)
        except ValueError:
            _fail(400, "invalid_input", "since must be an ISO time.")
        rows = await db(store.cases, created_after=after, limit=100)
        return {"count": len(rows), "latest": [views.case_row(r) for r in rows[:10]], "now": views.iso(now())}

    return router


def mount_console(app: FastAPI, store: ConsoleStore | None, settings: ConsoleSettings) -> None:
    """The API, then the single-page app for /console and everything under it (invite links included)."""

    @app.exception_handler(ConsoleError)
    async def console_error(request: Request, exc: ConsoleError) -> JSONResponse:
        return JSONResponse(exc.body, status_code=exc.status)

    app.include_router(console_router(store, settings))

    async def page(path: str = ""):
        if path.startswith("api/"):  # an unknown API path: never answer it with the page
            return JSONResponse({"error": "not_found", "detail": "Unknown console API path."}, status_code=404)
        if not CONSOLE_PAGE.is_file():
            return JSONResponse({"error": "console_not_built", "detail": "The console page isn't built yet."},
                                status_code=404)
        return FileResponse(CONSOLE_PAGE, headers={"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                                                   "Referrer-Policy": "same-origin", "Cache-Control": "no-store"})

    app.add_api_route("/console", page, methods=["GET"], include_in_schema=False)
    app.add_api_route("/console/{path:path}", page, methods=["GET"], include_in_schema=False)
