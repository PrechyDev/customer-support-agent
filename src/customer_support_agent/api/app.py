"""The public app: Vapi's Custom LLM endpoint, Vapi's event webhook, and a health check (SPECS §1, §2b, §11)."""

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing, asynccontextmanager
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from customer_support_agent.agent import fallbacks
from customer_support_agent.agent.session import AgentEvent, TextDelta, TurnResult
from customer_support_agent.api.auth import check_vapi_secret, describe_auth_header
from customer_support_agent.api.heard import heard_note
from customer_support_agent.api.openai_format import RequestError, completion, parse_request, sse_chunk, sse_done

logger = logging.getLogger(__name__)

MODEL_NAME = "relaypay-agent"  # what Vapi sees; the real model is AGENT_MODEL
SECRET_HEADER = "x-relaypay-secret"


class Manager(Protocol):
    def ask(self, conversation_id: str, message: str) -> AsyncIterator[AgentEvent]: ...
    async def prewarm(self, conversation_id: str) -> None: ...
    async def close(self, conversation_id: str) -> None: ...
    async def run_idle_reaper(self, interval_seconds: float = 30) -> None: ...
    async def close_all(self) -> None: ...

# Vapi event statuses that mean a call is starting / has ended.
_STARTING = ("queued", "ringing", "in-progress")


def _vapi_auth(request: Request, secret: str) -> str | None:
    """Which way the Vapi secret arrived, or None. The shared Vapi org's Custom LLM key always fills
    Authorization, so the assistant sends ours in its own header; Authorization works on a private org."""
    return check_vapi_secret(request.headers.get("authorization"), secret) or (
        "custom-header" if check_vapi_secret(request.headers.get(SECRET_HEADER), secret) == "raw" else None)


def _reject(request: Request, secret: str) -> JSONResponse:
    other = sorted(h for h in request.headers if any(w in h for w in ("auth", "key", "token", "secret")))
    logger.warning(
        "Rejected Vapi request to %s: missing or invalid secret (client=%s, authorization=%s, %s=%s, "
        "expected %d chars, other auth-like headers=%s)",
        request.url.path, request.client.host if request.client else "unknown",
        describe_auth_header(request.headers.get("authorization")), SECRET_HEADER,
        describe_auth_header(request.headers.get(SECRET_HEADER)), len(secret), other,
    )
    return JSONResponse({"error": "unauthorized"}, status_code=401)


def create_app(manager: Manager, vapi_secret: str,
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
    last_sent: dict[str, str] = {}  # call ID -> what we sent last turn (for "what the caller actually heard")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/chat/completions")
    async def chat_completions(request: Request):
        nonlocal auth_format_logged
        started = time.perf_counter()

        auth_format = _vapi_auth(request, vapi_secret)
        if auth_format is None:
            return _reject(request, vapi_secret)
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
        message = parsed.message
        note = heard_note(last_sent.get(call_id), parsed.last_assistant)
        if note:
            logger.info("Caller interrupted the last reply; telling the agent what they heard (conversation=%s)", call_id)
            message = f"{note}\n{message}"

        def remember(text: str) -> None:
            last_sent[call_id] = text

        events = manager.ask(call_id, message)
        if parsed.stream:
            ladder = [(reassure_after, fallbacks.REASSURANCE)]
            return StreamingResponse(_stream(events, call_id, chunk_id, started, ladder, remember),
                                     media_type="text/event-stream")
        return JSONResponse(await _collect(events, call_id, chunk_id, started, remember))

    background: set[asyncio.Task[None]] = set()  # keeps prewarm/close tasks alive until they finish

    def run_in_background(coro) -> None:
        task = asyncio.create_task(coro)
        background.add(task)
        task.add_done_callback(background.discard)

    @app.post("/vapi/events")
    async def vapi_events(request: Request):
        """Vapi's server webhook (assistant.server). Only status-update and end-of-call-report are
        subscribed. A call starting prewarms its agent session; a call ending closes it."""
        if _vapi_auth(request, vapi_secret) is None:
            return _reject(request, vapi_secret)
        try:
            message = (await request.json())["message"]
            kind, call_id = message.get("type"), (message.get("call") or {}).get("id")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            logger.warning("Rejected Vapi event: bad body (%s)", exc)
            return JSONResponse({"error": "bad_request"}, status_code=400)

        if call_id and kind == "status-update" and message.get("status") in _STARTING:
            run_in_background(manager.prewarm(str(call_id)))  # answer Vapi at once; the engine starts meanwhile
        elif call_id and (kind == "end-of-call-report" or (kind == "status-update" and message.get("status") == "ended")):
            last_sent.pop(str(call_id), None)
            run_in_background(manager.close(str(call_id)))
        logger.debug("Vapi event: type=%s status=%s call=%s", kind, message.get("status"), call_id)
        return {"ok": True}

    return app


async def _stream(events: AsyncIterator[AgentEvent], call_id: str, chunk_id: str, started: float,
                  ladder: list[tuple[float, str]], remember: Callable[[str], None]) -> AsyncIterator[str]:
    """Streams the agent's reply (SPECS §2b).

    - No filler: answers take 2-5 s. Only a genuinely slow turn (no reply text at 10 s) hears one
      reassurance line. The turn itself times out at 15 s.
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
        remember("".join(sent))
        _log_turn(call_id, started, first_text_ms, result, waiting_lines, "".join(sent))


async def _collect(events: AsyncIterator[AgentEvent], call_id: str, chunk_id: str, started: float,
                   remember: Callable[[str], None]) -> dict[str, Any]:
    parts: list[str] = []
    result: TurnResult | None = None
    async with aclosing(events) as agent:
        async for event in agent:
            if isinstance(event, TextDelta):
                parts.append(event.text)
            elif isinstance(event, TurnResult):
                result = event
    remember("".join(parts))
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
