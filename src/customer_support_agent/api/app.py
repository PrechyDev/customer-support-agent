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
from customer_support_agent.agent.grounding import assess
from customer_support_agent.agent.phrase_check import flag_caller, flag_phrases, is_filler
from customer_support_agent.agent.session import AgentEvent, TextDelta, TurnResult
from customer_support_agent.agent.spoken import forget as forget_spoken
from customer_support_agent.agent.spoken import remember as remember_spoken
from customer_support_agent.api.auth import check_vapi_secret, describe_auth_header
from customer_support_agent.api.caller import caller_from_vapi
from customer_support_agent.api.heard import heard_note
from customer_support_agent.api.openai_format import RequestError, completion, parse_request, sse_chunk, sse_done
from customer_support_agent.api.records import CallRecorder
from customer_support_agent.api.web import mount_web
from customer_support_agent.api.console import mount_console
from customer_support_agent.config import ConsoleSettings, VoiceSettings
from customer_support_agent.db.console_store import ConsoleStore
from customer_support_agent.db.repository import RepositoryUnavailable

logger = logging.getLogger(__name__)

MODEL_NAME = "relaypay-agent"  # what Vapi sees; the real model is AGENT_MODEL
SECRET_HEADER = "x-relaypay-secret"

TurnDone = Callable[[TurnResult | None, str, float | None], None]  # (result, text sent, first_text_ms)


class Manager(Protocol):
    def ask(self, conversation_id: str, message: str, caller: dict | None = None) -> AsyncIterator[AgentEvent]: ...
    async def prewarm(self, conversation_id: str, caller: dict | None = None) -> None: ...
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
               reassure_after: float = fallbacks.REASSURANCE_AFTER_SECONDS,
               filler_wait: float = fallbacks.FILLER_WAIT_SECONDS,
               recorder: CallRecorder | None = None, voice: VoiceSettings | None = None,
               console: ConsoleSettings | None = None,
               repo: Any | None = None) -> FastAPI:
    recorder = recorder or CallRecorder(None)  # no database: nothing is recorded, calls still work

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        reaper = asyncio.create_task(manager.run_idle_reaper())
        yield
        reaper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reaper
        await manager.close_all()
        await recorder.wait()

    app = FastAPI(title="RelayPay support backend", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    auth_format_logged = False
    last_sent: dict[str, str] = {}  # call ID -> what we sent last turn (for "what the caller actually heard")
    flagged: dict[str, set[str]] = {}  # call ID -> event types already logged from the caller's words
    callers: dict[str, dict | None] = {}  # call ID -> pre-call form, from the first request or event that has it

    def caller_for(call_id: str, body: Any) -> dict | None:
        """The call's form data; the call's row is created the first time the call is seen."""
        if call_id not in callers or callers[call_id] is None:
            first_seen = call_id not in callers
            callers[call_id] = caller_from_vapi(body)
            if first_seen or callers[call_id] is not None:
                recorder.started(call_id, callers[call_id])
        return callers[call_id]

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness: the process is up. Cheap, so a database outage doesn't make Cloud Run restart us."""
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready():
        """Readiness: the database answers within 2 s."""
        if repo is None:
            return JSONResponse({"status": "degraded", "database": "not configured"}, status_code=503)
        try:
            await asyncio.wait_for(asyncio.to_thread(repo.ping), timeout=2)
            return {"status": "ok", "database": "ok"}
        except (RepositoryUnavailable, TimeoutError):
            logger.warning("Readiness check failed: database unavailable")
            return JSONResponse({"status": "degraded", "database": "unavailable"}, status_code=503)

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

        caller = caller_for(call_id, body)
        for event_type in flag_caller(parsed.message):  # on record even if the agent doesn't log it
            if event_type not in flagged.setdefault(call_id, set()):
                flagged[call_id].add(event_type)
                recorder.event(call_id, event_type, f"Caller said: {parsed.message[:150]}")

        def on_done(result: TurnResult | None, sent: str, first_text_ms: float | None) -> None:
            last_sent[call_id] = sent
            remember_spoken(call_id, sent)  # lets a tool see what the caller just heard read back
            checked = assess(result, sent)
            note = checked.note
            flags = flag_phrases(sent)  # log-only: the reply is already spoken
            if flags:
                note = f"{note} PHRASE FLAG: {', '.join(flags)}."
                logger.warning("Phrase check flagged the reply (conversation=%s): %s", call_id, ", ".join(flags))
            _log_turn(call_id, started, first_text_ms, result, sent, checked.answer_type, checked.grounded)
            if result is None and not sent:
                # Vapi guessed the caller had finished, then cancelled and resent the full sentence:
                # nothing was said, so it isn't a turn (the resent request is recorded instead).
                return
            recorder.turn(call_id, caller, parsed.message, sent, checked.answer_type, note,
                          first_text_ms, _ms_since(started))

        if is_filler(parsed.message):
            # "Um, I.": Vapi sent a pause as a turn. Answering it talks over the caller, and an empty reply
            # seemed to leave Vapi stuck (25 s of silence in a test). So hold the request: if the caller keeps
            # talking, Vapi cancels it and resends the full sentence; if not, a short "Mm-hm?" after a moment.
            logger.info("Caller only paused (%d words of filler); holding, not sent to the agent (conversation=%s)",
                        len(parsed.message.split()), call_id)
            events = _fixed_line(fallbacks.FILLER_ACK, delay=filler_wait)
        elif len(parsed.message) > fallbacks.MAX_MESSAGE_CHARS:  # checked on the caller's own words, before Claude
            logger.warning("Caller message too long (%d chars); not sent to the agent (conversation=%s)",
                           len(parsed.message), call_id)
            events = _fixed_line(fallbacks.TOO_LONG)
        else:
            events = manager.ask(call_id, message, caller)
        if parsed.stream:
            ladder = [(reassure_after, fallbacks.REASSURANCE)]
            return StreamingResponse(_stream(events, chunk_id, started, ladder, on_done),
                                     media_type="text/event-stream")
        return JSONResponse(await _collect(events, chunk_id, started, on_done))

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
            caller = caller_for(str(call_id), message)
            run_in_background(manager.prewarm(str(call_id), caller))  # answer Vapi at once; the engine starts meanwhile
        elif call_id and (kind == "end-of-call-report" or (kind == "status-update" and message.get("status") == "ended")):
            logger.info("Call ended (conversation=%s event=%s reason=%s)", call_id, kind,
                        message.get("endedReason") or (message.get("call") or {}).get("endedReason") or "not given")
            last_sent.pop(str(call_id), None)
            forget_spoken(str(call_id))
            callers.pop(str(call_id), None)
            flagged.pop(str(call_id), None)
            analysis = message.get("analysis") if isinstance(message.get("analysis"), dict) else {}
            summary = analysis.get("summary") if isinstance(analysis.get("summary"), str) else None
            recorder.ended(str(call_id), summary)  # Vapi's end-of-call summary (analysisPlan.summaryPlan)
            run_in_background(manager.close(str(call_id)))
        logger.debug("Vapi event: type=%s status=%s call=%s", kind, message.get("status"), call_id)
        return {"ok": True}

    mount_web(app, voice or VoiceSettings(None, None), repo)  # the voice page and its API
    mount_console(app, ConsoleStore(repo) if repo is not None else None,
                  console or ConsoleSettings(None, None))  # the support console and its API
    return app


async def _stream(events: AsyncIterator[AgentEvent], chunk_id: str, started: float,
                  ladder: list[tuple[float, str]], on_done: TurnDone) -> AsyncIterator[str]:
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
        if waiting_lines:
            logger.info("Slow turn: the caller heard %d reassurance line(s)", waiting_lines)
        on_done(result, "".join(sent), first_text_ms)


async def _collect(events: AsyncIterator[AgentEvent], chunk_id: str, started: float, on_done: TurnDone) -> dict[str, Any]:
    parts: list[str] = []
    result: TurnResult | None = None
    async with aclosing(events) as agent:
        async for event in agent:
            if isinstance(event, TextDelta):
                parts.append(event.text)
            elif isinstance(event, TurnResult):
                result = event
    on_done(result, "".join(parts), _ms_since(started) if parts else None)
    return completion("".join(parts), chunk_id=chunk_id, model=MODEL_NAME)


async def _fixed_line(line: str, delay: float = 0.0) -> AsyncIterator[AgentEvent]:
    """A reply from the backend alone, shaped like an agent turn so it streams and is logged the same way.
    With a delay, Vapi can cancel the request first (the caller kept talking), and then nothing is said."""
    if delay:
        await asyncio.sleep(delay)
    yield TextDelta(line)
    yield TurnResult(outcome="ok", fallback=line)


def _ms_since(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _log_turn(call_id: str, started: float, first_text_ms: float | None, result: TurnResult | None,
              sent_text: str, answer_type: str, grounded: bool | None) -> None:
    """One line per caller message: the numbers for the latency comparison, and the grounding check."""
    logger.log(
        logging.WARNING if grounded is False else logging.INFO,
        "Vapi turn (conversation=%s first_text_ms=%s total_ms=%s outcome=%s type=%s grounded=%s turns=%s "
        "tools=%s cost_usd=%s ends_call=%s)",
        call_id, first_text_ms, _ms_since(started), result.outcome if result else "cancelled", answer_type,
        grounded, result.num_turns if result else None, [t.rsplit("__", 1)[-1] for t in result.tools_used] if result else [],
        result.cost_usd if result else None, result.ends_call if result else False,
    )
    # Exactly what Vapi received, to compare word by word with Vapi's transcript. DEBUG only:
    # replies can repeat customer details, so they stay out of normal logs (LOG_LEVEL=DEBUG).
    logger.debug("Sent to Vapi (conversation=%s): %r", call_id, sent_text)
