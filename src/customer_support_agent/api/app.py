"""The public app: Vapi's Custom LLM endpoint plus a health check (SPECS §1, §11)."""

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from customer_support_agent.agent.session import AgentEvent, TextDelta, TurnResult
from customer_support_agent.api.auth import check_vapi_secret
from customer_support_agent.api.openai_format import RequestError, completion, parse_request, sse_chunk, sse_done

logger = logging.getLogger(__name__)

MODEL_NAME = "relaypay-agent"  # what Vapi sees; the real model is AGENT_MODEL


class Manager(Protocol):
    def ask(self, conversation_id: str, message: str) -> AsyncIterator[AgentEvent]: ...
    async def run_idle_reaper(self, interval_seconds: float = 30) -> None: ...
    async def close_all(self) -> None: ...


def create_app(manager: Manager, vapi_secret: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        reaper = asyncio.create_task(manager.run_idle_reaper())
        yield
        reaper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reaper
        await manager.close_all()

    app = FastAPI(title="RelayPay support backend", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    auth_format_logged = False

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/chat/completions")
    async def chat_completions(request: Request):
        nonlocal auth_format_logged
        started = time.perf_counter()

        auth_format = check_vapi_secret(request.headers.get("authorization"), vapi_secret)
        if auth_format is None:
            logger.warning("Rejected Vapi request: missing or invalid secret (client=%s)",
                           request.client.host if request.client else "unknown")
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if not auth_format_logged:  # tells us which format Vapi uses, once
            logger.info("Vapi auth header format: %s", auth_format)
            auth_format_logged = True

        try:
            body = await request.json()
            parsed = parse_request(body)
        except (ValueError, RequestError) as exc:
            logger.warning("Rejected Vapi request: %s", exc)
            return JSONResponse({"error": "bad_request", "detail": str(exc)}, status_code=400)

        call_id = parsed.call_id
        if not call_id:
            call_id = f"no-call-id-{uuid.uuid4().hex}"
            logger.warning("Vapi request has no call.id (top-level keys: %s); this turn won't remember earlier ones",
                           sorted(body))

        chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
        events = manager.ask(call_id, parsed.message)
        if parsed.stream:
            return StreamingResponse(_stream(events, call_id, chunk_id, started), media_type="text/event-stream")
        return JSONResponse(await _collect(events, call_id, chunk_id, started))

    return app


async def _stream(events: AsyncIterator[AgentEvent], call_id: str, chunk_id: str, started: float) -> AsyncIterator[str]:
    """Streams text as it arrives. If Vapi hangs up mid-reply (barge-in), closing `events` interrupts the engine."""
    first_text_ms: float | None = None
    result: TurnResult | None = None
    async with aclosing(events) as agent:
        try:
            async for event in agent:
                if isinstance(event, TextDelta):
                    if first_text_ms is None:
                        first_text_ms = _ms_since(started)
                    yield sse_chunk(event.text, chunk_id=chunk_id, model=MODEL_NAME)
                else:
                    result = event
            yield sse_chunk(None, chunk_id=chunk_id, model=MODEL_NAME, finish=True)
            yield sse_done()
        finally:
            _log_turn(call_id, started, first_text_ms, result)


async def _collect(events: AsyncIterator[AgentEvent], call_id: str, chunk_id: str, started: float) -> dict[str, Any]:
    parts: list[str] = []
    result: TurnResult | None = None
    async with aclosing(events) as agent:
        async for event in agent:
            if isinstance(event, TextDelta):
                parts.append(event.text)
            else:
                result = event
    _log_turn(call_id, started, _ms_since(started) if parts else None, result)
    return completion("".join(parts), chunk_id=chunk_id, model=MODEL_NAME)


def _ms_since(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _log_turn(call_id: str, started: float, first_text_ms: float | None, result: TurnResult | None) -> None:
    """One line per caller message: the numbers for the latency comparison."""
    logger.info(
        "Vapi turn (conversation=%s first_text_ms=%s total_ms=%s outcome=%s turns=%s cost_usd=%s)",
        call_id, first_text_ms, _ms_since(started),
        result.outcome if result else "cancelled", result.num_turns if result else None,
        result.cost_usd if result else None,
    )
