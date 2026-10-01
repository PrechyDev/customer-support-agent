"""The call's own records in Supabase: the conversation row, one row per turn, and how it ended.

Every write runs in a worker thread in the background, so the caller never waits for the database, and
a failed write is logged, never raised: a call keeps working when the database is down (the tools
then say so). Without a repository (no DATABASE_URL), nothing is written.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from customer_support_agent.db.repository import RepositoryUnavailable

logger = logging.getLogger(__name__)


class CallRecorder:
    def __init__(self, repo: Any | None, model: str | None = None) -> None:
        self._repo = repo
        self._model = model
        self._ensured: set[str] = set()  # calls whose conversation row exists
        self._tasks: set[asyncio.Task] = set()

    def started(self, cid: str, caller: dict | None) -> None:
        self._background(cid, "start", lambda: self._ensure(cid, caller))

    def turn(self, cid: str, caller: dict | None, user_transcript: str, assistant_response: str, answer_type: str,
             confidence_note: str, first_text_ms: float | None, total_ms: float) -> None:
        def write() -> None:
            self._ensure(cid, caller)  # the turn row needs the conversation row first
            self._repo.log_turn(cid, user_transcript, assistant_response, answer_type, confidence_note,
                                first_text_ms, total_ms)
        self._background(cid, "turn", write)

    def event(self, cid: str, event_type: str, summary: str) -> None:
        self._background(cid, "event", lambda: self._repo.log_event(cid, event_type, summary, {"source": "backend"}))

    def ended(self, cid: str, summary: str | None) -> None:
        self._background(cid, "end", lambda: self._repo.close_conversation(cid, summary))

    def abandoned(self, cid: str) -> None:
        self._background(cid, "abandon", lambda: self._repo.mark_abandoned(cid))

    async def wait(self) -> None:
        """Lets pending writes finish (shutdown, tests)."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def _ensure(self, cid: str, caller: dict | None) -> None:
        if cid not in self._ensured:
            self._repo.ensure_conversation(cid, model=self._model, caller=caller)
            self._ensured.add(cid)

    def _background(self, cid: str, what: str, work: Callable[[], None]) -> None:
        if self._repo is None:
            return

        def run() -> None:
            try:
                work()
            except RepositoryUnavailable:
                logger.warning("Could not record call %s: database unavailable (conversation=%s)", what, cid)
            except Exception:
                logger.exception("Could not record call %s (conversation=%s)", what, cid)

        try:
            task = asyncio.create_task(asyncio.to_thread(run))
        except RuntimeError:  # no running event loop (shutdown): the record is lost, but say so
            logger.warning("Could not record call %s: backend shutting down (conversation=%s)", what, cid)
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
