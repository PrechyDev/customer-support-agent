"""One call's agent session: send the caller's words in, stream Claude's reply out.

`ask()` yields TextDelta pieces as the reply is written, then exactly one TurnResult.
It never raises: every failure becomes a TurnResult with an outcome the caller of
this module can act on (SessionManager turns outcomes into spoken fallback lines).
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from claude_agent_sdk.types import StreamEvent

logger = logging.getLogger(__name__)

Outcome = Literal["ok", "max_turns", "error", "timeout", "busy"]


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class TurnResult:
    outcome: Outcome
    text: str = ""  # what the model said (fallback lines are not included)
    tools_used: tuple[str, ...] = ()
    num_turns: int = 0
    cost_usd: float | None = None
    duration_ms: float = 0.0
    error: str | None = None
    fallback: str | None = None  # the fixed line spoken instead of / after the model's text


AgentEvent = TextDelta | TurnResult


class AgentClient(Protocol):
    """The parts of ClaudeSDKClient we use. Tests pass a fake."""

    async def connect(self) -> None: ...
    async def query(self, prompt: str) -> None: ...
    def receive_response(self) -> AsyncIterator[Any]: ...
    async def interrupt(self) -> None: ...
    async def disconnect(self) -> None: ...


_DONE = object()


def _text_delta(event: dict[str, Any]) -> str | None:
    if event.get("type") != "content_block_delta":
        return None
    delta = event.get("delta") or {}
    return delta.get("text") if delta.get("type") == "text_delta" else None


class _Turn:
    """What we learn while one turn's messages arrive."""

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.tools: list[str] = []
        self.result: ResultMessage | None = None
        self._streamed_this_message = False
        self._spoke_before = False

    def on_message(self, message: Any) -> list[str]:
        """Returns the text pieces to speak for this message."""
        if isinstance(message, StreamEvent):
            piece = _text_delta(message.event)
            if not piece:
                return []
            prefix = " " if self._spoke_before and not self._streamed_this_message else ""
            self._streamed_this_message = True
            return [prefix + piece]

        if isinstance(message, AssistantMessage):
            message_text = " ".join(b.text for b in message.content if isinstance(b, TextBlock)).strip()
            self.tools += [b.name for b in message.content if isinstance(b, ToolUseBlock)]
            to_speak = []
            if message_text:
                self.texts.append(message_text)
                if not self._streamed_this_message:  # no deltas arrived: speak the whole block
                    to_speak.append((" " if self._spoke_before else "") + message_text)
                self._spoke_before = True
            self._streamed_this_message = False
            return to_speak

        if isinstance(message, ResultMessage):
            self.result = message
        return []


class AgentSession:
    def __init__(self, client: AgentClient, conversation_id: str, turn_timeout_seconds: float) -> None:
        self._client = client
        self.conversation_id = conversation_id
        self._timeout = turn_timeout_seconds

    async def start(self) -> None:
        """Starts the engine and connects to MCP. Errors propagate: the manager decides what the caller hears."""
        started = time.perf_counter()
        await self._client.connect()
        logger.info("Agent session started (conversation=%s, %.0f ms)", self.conversation_id,
                    (time.perf_counter() - started) * 1000)

    async def close(self) -> None:
        try:
            await self._client.disconnect()
            logger.info("Agent session closed (conversation=%s)", self.conversation_id)
        except Exception:
            logger.exception("Error closing agent session (conversation=%s)", self.conversation_id)

    async def ask(self, message: str) -> AsyncIterator[AgentEvent]:
        started = time.perf_counter()
        turn = _Turn()
        queue: asyncio.Queue[Any] = asyncio.Queue()
        pump = asyncio.create_task(self._pump(message, queue))
        deadline = asyncio.get_running_loop().time() + self._timeout
        outcome: Outcome = "ok"
        error: str | None = None
        engine_running = True  # until the engine reports it's done, or we've stopped it

        try:
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                item = await asyncio.wait_for(queue.get(), timeout=max(remaining, 0))
                if item is _DONE:
                    engine_running = False
                    break
                if isinstance(item, BaseException):
                    raise item
                for piece in turn.on_message(item):
                    yield TextDelta(piece)
            outcome, error = self._outcome(turn.result)
        except TimeoutError:
            outcome, error = "timeout", f"no reply within {self._timeout} s"
        except Exception as exc:
            outcome, error = "error", f"{type(exc).__name__}: {exc}"
            logger.exception("Agent turn failed (conversation=%s)", self.conversation_id)
        finally:
            # Also runs when the reader stops early: the caller talked over the agent and Vapi
            # dropped the request. Stop the engine so the next message doesn't wait for a reply nobody hears.
            if engine_running:
                if outcome == "ok":
                    logger.info("Agent turn cancelled mid-reply (conversation=%s)", self.conversation_id)
                await self._interrupt()
            if not pump.done():
                pump.cancel()

        result = TurnResult(
            outcome=outcome,
            text=" ".join(turn.texts),
            tools_used=tuple(turn.tools),
            num_turns=turn.result.num_turns if turn.result else 0,
            cost_usd=turn.result.total_cost_usd if turn.result else None,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            error=error,
        )
        logger.info(
            "Agent turn (conversation=%s outcome=%s turns=%d tools=%s cost_usd=%s duration_ms=%.0f)",
            self.conversation_id, result.outcome, result.num_turns, list(result.tools_used),
            result.cost_usd, result.duration_ms,
        )
        yield result

    async def _pump(self, message: str, queue: asyncio.Queue[Any]) -> None:
        """Reads SDK messages into the queue, so the reader can apply one deadline to the whole turn."""
        try:
            await self._client.query(message)
            async for item in self._client.receive_response():
                await queue.put(item)
        except Exception as exc:  # handed to the reader, which reports it
            await queue.put(exc)
        finally:
            await queue.put(_DONE)

    async def _interrupt(self) -> None:
        try:
            await self._client.interrupt()
        except Exception:
            logger.exception("Could not interrupt timed-out turn (conversation=%s)", self.conversation_id)

    @staticmethod
    def _outcome(result: ResultMessage | None) -> tuple[Outcome, str | None]:
        if result is None:
            return "error", "no result message from the agent"
        if result.subtype == "error_max_turns":
            return "max_turns", None
        if result.is_error or result.subtype != "success":
            return "error", f"{result.subtype}: {result.errors or ''}".strip()
        return "ok", None
