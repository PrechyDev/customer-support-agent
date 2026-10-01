"""The voice page and its small API (FRONTEND_PLAN §4, §5.1).

The browser only ever talks to these endpoints, never to Supabase, and only Vapi's PUBLIC key reaches it.
"""

import asyncio
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictBool

from customer_support_agent.api.ratelimit import RateLimiter, client_ip
from customer_support_agent.config import VoiceSettings
from customer_support_agent.db.repository import RepositoryUnavailable
from customer_support_agent.domain.callbacks import CallbackError, spoken_window
from customer_support_agent.domain.normalise import mask_email

logger = logging.getLogger(__name__)

CALL_ID = re.compile(r"[A-Za-z0-9-]{1,64}")  # Vapi call IDs are UUIDs
RECENT = timedelta(hours=2)  # the page only sees the outcome of a call that just happened

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"
# Pages only: no framing (clickjacking), no MIME sniffing, the mic for this site only.
PAGE_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                "Referrer-Policy": "same-origin", "Permissions-Policy": "microphone=(self), camera=()"}


def _error(status: int, error: str) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=status)


class Rating(BaseModel):
    helpful: StrictBool


def outcome_from_record(row: dict) -> dict:
    """What the voice page shows after the call (FRONTEND_PLAN §4.5). Never a name, phone or full email."""
    out: dict[str, Any] = {"outcome": "none", "reference": None, "callback": None, "email_masked": None}
    if row.get("escalation_id"):
        if row.get("contact_method") == "call":
            window = None
            stored = ("callback_start_utc", "callback_end_utc", "callback_timezone")
            if row.get("call_booked") and all(row.get(key) for key in stored):
                try:
                    window = spoken_window(row["callback_start_utc"], row["callback_end_utc"], row["callback_timezone"])
                except CallbackError as exc:
                    logger.warning("Outcome without its callback window (%s): %s", row["escalation_id"], exc)
            return {**out, "outcome": "callback", "reference": row["escalation_id"], "callback": window}
        email = row.get("user_email")
        return {**out, "outcome": "email", "reference": row["escalation_id"],
                "email_masked": mask_email(email) if email else None}
    if row.get("ticket_id"):
        return {**out, "outcome": "ticket", "reference": row["ticket_id"]}
    return out


CALL_LOOKUPS_PER_MINUTE = 60  # a page polls the outcome a few times per call


def voice_router(voice: VoiceSettings, repo: Any | None = None,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> APIRouter:
    router = APIRouter()
    limiter = RateLimiter(limit=CALL_LOOKUPS_PER_MINUTE, window_seconds=60)  # these are public: stop guessing/flooding

    async def recent_call(call_id: str, request: Request) -> dict | JSONResponse:
        """The call's outcome row, or the error response: 404 unless it started in the last 2 hours."""
        if limiter.hit(client_ip(request)):
            logger.warning("Voice call lookups rate-limited for one client")
            return _error(429, "too_many_requests")
        if repo is None:
            return _error(503, "records_unavailable")
        if not CALL_ID.fullmatch(call_id):
            return _error(404, "not_found")
        try:
            row = await asyncio.to_thread(repo.voice_outcome, call_id)
        except RepositoryUnavailable:
            logger.warning("Voice outcome unavailable: database down (conversation=%s)", call_id)
            return _error(503, "records_unavailable")
        if row is None or row["started_at"] < now() - RECENT:
            return _error(404, "not_found")
        return row

    @router.get("/", include_in_schema=False)
    async def voice_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "voice" / "index.html", headers=PAGE_HEADERS)

    @router.get("/voice/config")
    async def voice_config():
        if not (voice.public_key and voice.assistant_id):
            logger.warning("Voice page can't start calls: VAPI_PUBLIC_KEY or VAPI_ASSISTANT_ID is not set")
            return _error(503, "voice_unavailable")
        return {"publicKey": voice.public_key, "assistantId": voice.assistant_id}

    @router.get("/voice/calls/{call_id}/outcome")
    async def call_outcome(call_id: str, request: Request):
        row = await recent_call(call_id, request)
        return row if isinstance(row, JSONResponse) else outcome_from_record(row)

    @router.post("/voice/calls/{call_id}/rating")
    async def rate_call(call_id: str, rating: Rating, request: Request):
        row = await recent_call(call_id, request)
        if isinstance(row, JSONResponse):
            return row
        try:
            saved = await asyncio.to_thread(repo.save_rating, call_id, "yes" if rating.helpful else "no")
        except RepositoryUnavailable:
            logger.warning("Rating not saved: database down (conversation=%s)", call_id)
            return _error(503, "records_unavailable")
        logger.info("Call rated %s (conversation=%s)%s", "helpful" if rating.helpful else "not helpful", call_id,
                    "" if saved else "; already rated, ignored")
        return {"ok": True}

    return router


def mount_web(app: FastAPI, voice: VoiceSettings, repo: Any | None = None) -> None:
    app.include_router(voice_router(voice, repo))
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
