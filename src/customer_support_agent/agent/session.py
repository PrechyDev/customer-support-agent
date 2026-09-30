"""One call's agent session: send the caller's words in, get Claude's spoken reply out (SPECS §2b).

`ask()` yields TextDelta pieces, then exactly one TurnResult. It never raises: every failure
becomes a TurnResult with an outcome the SessionManager turns into a spoken line.

Three rules from the conversation-flow design:
- Only words inside <say>...</say> are spoken. Anything else the model writes (reasoning, notes) is
  dropped, so its thinking can never reach the caller (Haiku reasoned out loud in a real call).
- The model never ends a call itself. It writes <end_call/> and the backend says the fixed goodbye.
  Vapi hangs up on "goodbye", so any hang-up phrase the model writes is rewritten (Haiku once greeted
  a caller with an earlier trigger phrase, and Vapi hung up mid-call).
- Complete messages: each model message is held until it ends. If it called a tool, its text was
  narration ("Let me search...") and is dropped; otherwise it's the answer and is sent whole.
- Clean cancellation: if a turn is abandoned (Vapi cancelled the request, or it timed out), the
  engine is interrupted and its leftover output is drained before the next turn starts. Without
  this, the next turn reads the old reply's leftovers as its own answer (found in real calls).
"""

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from claude_agent_sdk.types import StreamEvent

logger = logging.getLogger(__name__)

Outcome = Literal["ok", "max_turns", "error", "timeout", "busy"]

DRAIN_TIMEOUT_SECONDS = 5.0  # longer than this and the session is replaced instead of reused
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_SAY = re.compile(r"<say>(.*?)(?:</say>|$)", re.DOTALL)
_END_CALL = "<end_call"
# The word Vapi hangs up on (fallbacks.END_CALL_PHRASE / endCallPhrases). The model's own words must
# never contain it: only the backend's fixed ending lines do.
_HANGUP_PHRASES = ((re.compile(r"\bgood-?bye\b", re.IGNORECASE), "bye for now"),)


def without_hangup_phrases(text: str) -> str:
    for pattern, replacement in _HANGUP_PHRASES:
        text = pattern.sub(replacement, text)
    return text.strip()


def say_text(raw: str, final: bool) -> str:
    """The spoken part of a model message: everything inside <say> tags, joined.

    While the message is still streaming (final=False), a half-written tag at the end ("</sa") is
    cut off so it's never spoken.
    """
    text = " ".join(part.strip() for part in _SAY.findall(raw))
    if not final and "<" in text[-7:]:
        text = text[: text.rfind("<")]
    return text.strip()


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class TurnResult:
    outcome: Outcome
    text: str = ""  # what the caller actually heard from the model (fallback lines not included)
    tools_used: tuple[str, ...] = ()
    num_turns: int = 0
    cost_usd: float | None = None
    duration_ms: float = 0.0
    error: str | None = None
    end_requested: bool = False  # the model wrote <end_call/>: the caller is done
    fallback: str | None = None  # the fixed line spoken instead of / after the model's text
    ends_call: bool = False  # the fallback line contains the end-call phrase, so Vapi hangs up


AgentEvent = TextDelta | TurnResult


class AgentClient(Protocol):
    """The parts of ClaudeSDKClient we use. Tests pass a fake."""

    async def connect(self) -> None: ...
    async def query(self, prompt: str) -> None: ...
    def receive_response(self) -> AsyncIterator[Any]: ...
    async def interrupt(self) -> None: ...
    async def disconnect(self) -> None: ...


_DONE = object()


class _Turn:
    """Turns the SDK's messages for one turn into speakable replies (SPECS §2b).

    - Only text inside <say> tags is spoken; reasoning outside them is dropped.
    - Before any tool has been called, each message is held until it ends: if it calls a tool, its
      text was narration and is dropped; otherwise its <say> text is sent whole.
    - After a tool result, the model is answering, so complete <say> sentences are sent as soon as
      they're written. Narration between two tool calls is rare; sentences already sent can't be taken back.
    """

    def __init__(self, conversation_id: str) -> None:
        self._conversation_id = conversation_id
        self.spoken: list[str] = []
        self.tools: list[str] = []
        self.result: ResultMessage | None = None
        self._saw_stream = False  # raw stream events arrived, so they (not full messages) drive speech
        self._raw = ""  # everything the model wrote in the current message
        self._sent = 0  # characters of this message's <say> text already spoken
        self._message_calls_tool = False
        self._tool_called = False  # any tool call so far in this turn
        self.end_requested = False

    def on_message(self, message: Any) -> list[AgentEvent]:
        if isinstance(message, StreamEvent):
            self._saw_stream = True
            return self._on_stream_event(message.event)
        if isinstance(message, AssistantMessage):
            self.tools += [b.name for b in message.content if isinstance(b, ToolUseBlock)]
            if self._saw_stream:
                return []  # already handled from the stream events
            raw = " ".join(b.text for b in message.content if isinstance(b, TextBlock))
            calls_tool = any(isinstance(b, ToolUseBlock) for b in message.content)
            self._raw, self._sent = raw, 0
            return self._drop() if calls_tool else self._finish()
        if isinstance(message, ResultMessage):
            self.result = message
        return []

    def _on_stream_event(self, event: dict[str, Any]) -> list[AgentEvent]:
        kind = event.get("type")
        if kind == "message_start":
            self._raw, self._sent, self._message_calls_tool = "", 0, False
        elif kind == "content_block_start" and (event.get("content_block") or {}).get("type") == "tool_use":
            self._message_calls_tool = self._tool_called = True
            return self._drop()
        elif kind == "content_block_delta":
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text") and not self._message_calls_tool:
                self._raw += delta["text"]
                if self._tool_called:  # answering after a tool: send finished sentences now
                    unsent = say_text(self._raw, final=False)[self._sent:]
                    *done, rest = _SENTENCE_END.split(unsent)
                    self._sent += len(unsent) - len(rest)  # everything before `rest` is now spoken
                    return [event for sentence in done for event in self._speak(sentence)]
        elif kind == "message_stop":
            return self._drop() if self._message_calls_tool else self._finish()
        return []

    def _finish(self) -> list[AgentEvent]:
        if _END_CALL in self._raw:
            self.end_requested = True
        spoken = say_text(self._raw, final=True)
        if self._raw.strip() and not spoken and not self.end_requested:
            logger.warning("Model reply had no <say> text; nothing spoken (conversation=%s)", self._conversation_id)
        outside = _SAY.sub("", self._raw).strip()
        if outside:
            logger.debug("Dropped text outside <say> (conversation=%s): %r", self._conversation_id, outside)
        events = self._speak(spoken[self._sent:])
        self._raw, self._sent = "", 0
        return events

    def _speak(self, text: str) -> list[AgentEvent]:
        safe = without_hangup_phrases(text)
        if safe != text.strip():
            logger.warning("Rewrote a hang-up phrase in the model's reply (conversation=%s): %r",
                           self._conversation_id, text)
        text = safe
        if not text:
            return []
        piece = (" " if self.spoken else "") + text
        self.spoken.append(text)
        return [TextDelta(piece)]

    def _drop(self) -> list[AgentEvent]:
        if self._raw.strip():
            logger.debug("Dropped narration before a tool call (conversation=%s): %r", self._conversation_id, self._raw)
        self._raw, self._sent = "", 0
        return []


class AgentSession:
    def __init__(self, client: AgentClient, conversation_id: str, turn_timeout_seconds: float) -> None:
        self._client = client
        self.conversation_id = conversation_id
        self._timeout = turn_timeout_seconds
        self._cleanup: asyncio.Task[None] | None = None  # drain of an abandoned turn
        self.broken = False  # the engine couldn't be brought back to a clean state

    async def start(self) -> None:
        """Starts the engine and connects to MCP. Errors propagate: the manager decides what the caller hears."""
        started = time.perf_counter()
        await self._client.connect()
        logger.info("Agent session started (conversation=%s, %.0f ms)", self.conversation_id,
                    (time.perf_counter() - started) * 1000)

    async def ready(self) -> bool:
        """Waits for any cleanup of an abandoned turn. False means replace this session."""
        if self._cleanup is not None:
            await self._cleanup
            self._cleanup = None
        return not self.broken

    async def close(self) -> None:
        try:
            if self._cleanup is not None and not self._cleanup.done():
                self._cleanup.cancel()
            await self._client.disconnect()
            logger.info("Agent session closed (conversation=%s)", self.conversation_id)
        except Exception:
            logger.exception("Error closing agent session (conversation=%s)", self.conversation_id)

    async def ask(self, message: str) -> AsyncIterator[AgentEvent]:
        started = time.perf_counter()
        turn = _Turn(self.conversation_id)
        queue: asyncio.Queue[Any] = asyncio.Queue()
        pump = asyncio.create_task(self._pump(message, queue))
        deadline = asyncio.get_running_loop().time() + self._timeout
        outcome: Outcome = "ok"
        error: str | None = None

        try:
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                item = await asyncio.wait_for(queue.get(), timeout=max(remaining, 0))
                if item is _DONE:
                    break
                if isinstance(item, BaseException):
                    raise item
                for event in turn.on_message(item):
                    yield event
            outcome, error = self._outcome(turn.result)
        except TimeoutError:
            outcome, error = "timeout", f"no reply within {self._timeout} s"
        except Exception as exc:
            outcome, error = "error", f"{type(exc).__name__}: {exc}"
            logger.exception("Agent turn failed (conversation=%s)", self.conversation_id)
        finally:
            if not pump.done():
                # Abandoned mid-turn (Vapi cancelled it, or it timed out). The drain runs as its own
                # task: the request that owns this code may be cancelled repeatedly, so it can't wait here.
                if outcome == "ok":
                    logger.info("Agent turn cancelled mid-reply (conversation=%s)", self.conversation_id)
                self._cleanup = asyncio.create_task(self._stop_and_drain(pump))

        result = TurnResult(
            outcome=outcome,
            text=" ".join(turn.spoken),
            tools_used=tuple(turn.tools),
            num_turns=turn.result.num_turns if turn.result else 0,
            cost_usd=turn.result.total_cost_usd if turn.result else None,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            error=error,
            end_requested=turn.end_requested,
        )
        logger.info(
            "Agent turn (conversation=%s outcome=%s turns=%d tools=%s cost_usd=%s duration_ms=%.0f)",
            self.conversation_id, result.outcome, result.num_turns, list(result.tools_used),
            result.cost_usd, result.duration_ms,
        )
        yield result

    async def _pump(self, message: str, queue: asyncio.Queue[Any]) -> None:
        """Reads one response from the SDK (it ends at the ResultMessage) into the queue."""
        try:
            await self._client.query(message)
            async for item in self._client.receive_response():
                logger.debug("Engine step (conversation=%s): %s", self.conversation_id, _describe(item))
                await queue.put(item)
        except Exception as exc:  # handed to the reader, which reports it
            await queue.put(exc)
        finally:
            await queue.put(_DONE)

    async def _stop_and_drain(self, pump: asyncio.Task[None]) -> None:
        """Interrupts the engine, then lets the pump read the rest of that response and throw it away."""
        try:
            await self._client.interrupt()
        except Exception:
            logger.exception("Could not interrupt abandoned turn (conversation=%s)", self.conversation_id)
        try:
            await asyncio.wait_for(asyncio.shield(pump), timeout=DRAIN_TIMEOUT_SECONDS)
            logger.debug("Drained abandoned turn (conversation=%s)", self.conversation_id)
        except TimeoutError:
            pump.cancel()
            self.broken = True
            logger.warning("Abandoned turn didn't finish draining; session will be replaced (conversation=%s)",
                           self.conversation_id)

    @staticmethod
    def _outcome(result: ResultMessage | None) -> tuple[Outcome, str | None]:
        if result is None:
            return "error", "no result message from the agent"
        if result.subtype == "error_max_turns":
            return "max_turns", None
        if result.is_error or result.subtype != "success":
            return "error", f"{result.subtype}: {result.errors or ''}".strip()
        return "ok", None


def _describe(item: Any) -> str:
    """Short, content-free description of an engine message, for debug logs."""
    if isinstance(item, StreamEvent):
        event = item.event
        block = (event.get("content_block") or {}).get("type")
        return f"stream:{event.get('type')}" + (f":{block}" if block else "")
    if isinstance(item, ResultMessage):
        return f"result:{item.subtype}"
    return type(item).__name__
