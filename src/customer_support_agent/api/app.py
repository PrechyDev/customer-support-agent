"""The public app: Vapi's Custom LLM endpoint plus a health check (SPECS §1, §11)."""

import asyncio
import contextlib
import logging
import random
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from customer_support_agent.agent import fallbacks
from customer_support_agent.agent.session import AgentEvent, TextDelta, TurnResult
from customer_support_agent.api.auth import check_vapi_secret, describe_auth_header
from customer_support_agent.api.openai_format import RequestError, completion, parse_request, sse_chunk, sse_done

logger = logging.getLogger(__name__)

MODEL_NAME = "relaypay-agent"  # what Vapi sees; the real model is AGENT_MODEL
SECRET_HEADER = "x-relaypay-secret"


class Manager(Protocol):
    def ask(self, conversation_id: str, message: str) -> AsyncIterator[AgentEvent]: ...
    async def run_idle_reaper(self, interval_seconds: float = 30) -> None: ...
    async def close_all(self) -> None: ...


def create_app(manager: Manager, vapi_secret: str, filler_after: float = fallbacks.FILLER_AFTER_SECONDS,
               reassure_after: float = fallbacks.REASSURANCE_AFTER_SECONDS) -> FastAPI:
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

        auth_header = request.headers.get("authorization")
        # The shared Vapi org's Custom LLM key always fills Authorization, so the assistant sends our
        # secret in its own header (model.headers). Authorization is still accepted on its own org.
        custom_header = request.headers.get(SECRET_HEADER)
        auth_format = check_vapi_secret(auth_header, vapi_secret) or (
            "custom-header" if check_vapi_secret(custom_header, vapi_secret) == "raw" else None)
        if auth_format is None:
            other = sorted(h for h in request.headers if any(w in h for w in ("auth", "key", "token", "secret")))
            logger.warning(
                "Rejected Vapi request: missing or invalid secret (client=%s, authorization=%s, %s=%s, "
                "expected %d chars, other auth-like headers=%s)",
                request.client.host if request.client else "unknown",
                describe_auth_header(auth_header), SECRET_HEADER, describe_auth_header(custom_header),
                len(vapi_secret), other,
            )
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
            ladder = [(filler_after, random.choice(fallbacks.FILLERS)), (reassure_after, fallbacks.REASSURANCE)]
            return StreamingResponse(_stream(events, call_id, chunk_id, started, ladder), media_type="text/event-stream")
        return JSONResponse(await _collect(events, call_id, chunk_id, started))

    return app


async def _stream(events: AsyncIterator[AgentEvent], call_id: str, chunk_id: str, started: float,
                  ladder: list[tuple[float, str]]) -> AsyncIterator[str]:
    """Streams the agent's reply, with the waiting ladder (SPECS §2b).

    - While no reply text has arrived, each ladder line is said once at its time (a filler at 2 s,
      a reassurance at 8 s), so a slow turn is never silence. Fast turns hear none of them.
    - If Vapi hangs up mid-reply (barge-in), closing `events` makes the session interrupt and drain the engine.
    """
    first_text_ms: float | None = None
    result: TurnResult | None = None
    sent: list[str] = []
    waiting_lines = 0
    pending: asyncio.Future[AgentEvent] | None = None
    agent = aiter(events)

    def chunk(text: str) -> str:
        sent.append(text)
        return sse_chunk(text, chunk_id=chunk_id, model=MODEL_NAME)

    try:
        while True:
            pending = asyncio.ensure_future(anext(agent))
            while first_text_ms is None and ladder:
                at, line = ladder[0]
                done, _ = await asyncio.wait({pending}, timeout=max(at - (time.perf_counter() - started), 0))
                if done:
                    break
                ladder.pop(0)
                waiting_lines += 1
                yield chunk(line + " ")
            try:
                event = await pending
            except StopAsyncIteration:
                pending = None
                break
            pending = None
            if isinstance(event, TextDelta):
                if first_text_ms is None:
                    first_text_ms = _ms_since(started)
                yield chunk(event.text)
            else:
                result = event
        yield sse_chunk(None, chunk_id=chunk_id, model=MODEL_NAME, finish=True)
        yield sse_done()
    finally:
        if pending is not None and not pending.done():  # stopped mid-turn: stop reading first
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending
        await agent.aclose()  # the session schedules its own interrupt + drain, so this never has to wait long
        _log_turn(call_id, started, first_text_ms, result, waiting_lines, "".join(sent))


async def _collect(events: AsyncIterator[AgentEvent], call_id: str, chunk_id: str, started: float) -> dict[str, Any]:
    parts: list[str] = []
    result: TurnResult | None = None
    async with aclosing(events) as agent:
        async for event in agent:
            if isinstance(event, TextDelta):
                parts.append(event.text)
            else:
                result = event
    _log_turn(call_id, started, _ms_since(started) if parts else None, result, 0, "".join(parts))
    return completion("".join(parts), chunk_id=chunk_id, model=MODEL_NAME)


def _ms_since(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _log_turn(call_id: str, started: float, first_text_ms: float | None, result: TurnResult | None,
              waiting_lines: int, sent_text: str) -> None:
    """One line per caller message: the numbers for the latency comparison."""
    logger.info(
        "Vapi turn (conversation=%s first_text_ms=%s total_ms=%s outcome=%s turns=%s cost_usd=%s "
        "ends_call=%s waiting_lines=%d)",
        call_id, first_text_ms, _ms_since(started),
        result.outcome if result else "cancelled", result.num_turns if result else None,
        result.cost_usd if result else None, result.ends_call if result else False, waiting_lines,
    )
    # Exactly what Vapi received, to compare word by word with Vapi's transcript. DEBUG only:
    # replies can repeat customer details, so they stay out of normal logs (LOG_LEVEL=DEBUG).
    logger.debug("Sent to Vapi (conversation=%s): %r", call_id, sent_text)
