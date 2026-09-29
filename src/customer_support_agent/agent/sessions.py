"""Keeps one agent session per call, and decides what the caller hears when a turn fails."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace

from customer_support_agent.agent import fallbacks
from customer_support_agent.agent.session import AgentEvent, AgentSession, TextDelta, TurnResult

logger = logging.getLogger(__name__)

SessionFactory = Callable[[str], Awaitable[AgentSession]]  # creates and starts a session for a call ID


@dataclass
class _Entry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # one turn at a time per call
    session: AgentSession | None = None
    last_used: float = 0.0
    max_turn_hits: int = 0


class SessionManager:
    def __init__(self, factory: SessionFactory, *, max_sessions: int, idle_seconds: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._factory = factory
        self._max_sessions = max_sessions
        self._idle_seconds = idle_seconds
        self._clock = clock
        self._entries: dict[str, _Entry] = {}

    @property
    def active_count(self) -> int:
        return len(self._entries)

    async def ask(self, conversation_id: str, message: str) -> AsyncIterator[AgentEvent]:
        if not message.strip():
            yield TextDelta(fallbacks.EMPTY_REPLY)
            yield TurnResult(outcome="ok", fallback=fallbacks.EMPTY_REPLY)
            return

        entry = self._entries.get(conversation_id)
        if entry is None:
            if len(self._entries) >= self._max_sessions:
                logger.warning("Refused new call: %d sessions already open", len(self._entries))
                yield TextDelta(fallbacks.BUSY)
                yield TurnResult(outcome="busy", fallback=fallbacks.BUSY)
                return
            # Registered before any await, so a second message for this call finds it and waits on the lock.
            entry = self._entries[conversation_id] = _Entry(last_used=self._clock())

        async with entry.lock:
            if entry.session is None:
                try:
                    entry.session = await self._factory(conversation_id)
                except Exception as exc:
                    logger.exception("Could not start agent session (conversation=%s)", conversation_id)
                    self._entries.pop(conversation_id, None)
                    yield TextDelta(fallbacks.TECHNICAL_PROBLEM)
                    yield TurnResult(outcome="error", error=f"session start failed: {exc}",
                                     fallback=fallbacks.TECHNICAL_PROBLEM)
                    return

            entry.last_used = self._clock()
            spoke = False
            async for event in entry.session.ask(message):
                if isinstance(event, TextDelta):
                    spoke = True
                    yield event
                    continue
                line = self._fallback_for(entry, event)
                if line:
                    yield TextDelta((" " if spoke else "") + line)
                yield replace(event, fallback=line)
            entry.last_used = self._clock()

    @staticmethod
    def _fallback_for(entry: _Entry, result: TurnResult) -> str | None:
        if result.outcome == "max_turns":
            entry.max_turn_hits += 1
            return fallbacks.MAX_TURNS_FIRST if entry.max_turn_hits == 1 else fallbacks.MAX_TURNS_REPEAT
        if result.outcome in ("error", "timeout"):
            return fallbacks.TECHNICAL_PROBLEM
        if result.outcome == "ok" and not result.text:
            return fallbacks.EMPTY_REPLY
        return None

    async def close(self, conversation_id: str) -> None:
        entry = self._entries.pop(conversation_id, None)
        if entry and entry.session:
            await entry.session.close()

    async def close_idle(self) -> list[str]:
        """Closes sessions idle longer than idle_seconds. Busy sessions (mid-turn) are left alone."""
        now = self._clock()
        idle = [cid for cid, e in self._entries.items()
                if now - e.last_used > self._idle_seconds and not e.lock.locked()]
        for cid in idle:
            logger.info("Closing idle agent session (conversation=%s)", cid)
            await self.close(cid)
        return idle

    async def close_all(self) -> None:
        for cid in list(self._entries):
            await self.close(cid)

    async def run_idle_reaper(self, interval_seconds: float = 30) -> None:
        """Background loop for the backend to run while it's up."""
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await self.close_idle()
            except Exception:
                logger.exception("Idle session cleanup failed")
