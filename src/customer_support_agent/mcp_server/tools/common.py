"""Shared by every business tool: one error shape, and tool-call logging that never slows the reply."""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from customer_support_agent.db.repository import RepositoryUnavailable

logger = logging.getLogger(__name__)

_background: set[asyncio.Task] = set()

# Caps per call (SPECS §9): stop abuse of one call spilling into the database or the support queue.
MAX_VERIFICATION_ATTEMPTS = 2
MAX_LOOKUP_MISSES = 3  # references not found per call, then lookups stop (guessing guard)
MAX_TICKETS = 3
MAX_ESCALATIONS = 2
TICKET_CATEGORIES = ("compliance", "account", "dispute", "payment", "other")
PRIORITIES = ("high", "medium", "low")


_pending: dict[tuple[str, str], str] = {}  # (call ID, "phone" | "email") -> value the tool read back last


def confirmed(cid: str, kind: str, value: str, said_yes: bool, heard: bool) -> bool:
    """One read-back, never two. Accepted when the caller said yes (said_yes) to THIS value, either because the
    tool read it back last time, or because it was in what Bex just said (heard). Otherwise the tool reads
    it back now: the value is remembered, and the caller confirms on the next call."""
    if said_yes and (heard or _pending.get((cid, kind)) == value):
        _pending.pop((cid, kind), None)
        return True
    _pending[(cid, kind)] = value
    return False


def error(code: str, hint: str) -> dict[str, Any]:
    """The only error shape the model sees: a code and what to do next. Never internal details."""
    return {"error": code, "hint": hint}


def _summary(result: dict[str, Any]) -> str:
    keep = {k: v for k, v in result.items() if k not in ("support_notes",)}  # internal notes stay out of logs
    return str(keep)[:300]


_call_locks: dict[str, list] = {}  # call ID -> [lock, number of tools holding or waiting for it]


async def _work(cid: str, work: Callable[[], dict[str, Any]], exclusive: bool) -> dict[str, Any]:
    """Capped tools (verification, tickets, escalations) run one at a time per call: the model may call
    two in parallel, and check-then-insert would let both pass a cap. One process serves all calls
    (Cloud Run max-instances 1), so an in-process lock is enough.

    The lock is removed only when no tool holds or waits for it. (Checking lock.locked() isn't enough:
    the lock reads as free for a moment while it's handed to the next waiter.)"""
    if not exclusive:
        return await asyncio.to_thread(work)
    entry = _call_locks.setdefault(cid, [asyncio.Lock(), 0])
    entry[1] += 1
    try:
        async with entry[0]:
            return await asyncio.to_thread(work)
    finally:
        entry[1] -= 1
        if entry[1] == 0:
            _call_locks.pop(cid, None)


async def run_tool(repo: Any, cid: str, name: str, purpose: str, input_summary: str,
                   work: Callable[[], dict[str, Any]], exclusive: bool = False) -> dict[str, Any]:
    """Runs the tool's blocking work in a worker thread, turns failures into error results, and logs
    the call to tool_calls in the background (the caller never waits for the log)."""
    started = time.perf_counter()
    try:
        if repo is None:  # started without DATABASE_URL: only the knowledge base works
            raise RepositoryUnavailable("no database configured")
        result = await _work(cid, work, exclusive)
    except RepositoryUnavailable:
        result = error("unavailable", "Account systems can't be reached right now. Apologise, and suggest "
                                      "the support options in the RelayPay dashboard.")
    except Exception:
        logger.exception("Tool %s failed (conversation=%s)", name, cid)
        result = error("internal_error", "Something went wrong. Apologise and offer to have a specialist help.")
    duration_ms = int((time.perf_counter() - started) * 1000)
    status = "error" if "error" in result else "ok"
    logger.info("Tool %s (conversation=%s status=%s %d ms)", name, cid, status, duration_ms)

    if repo is not None:
        def log() -> None:
            try:
                repo.log_tool_call(cid, name, purpose, input_summary, _summary(result), status,
                                   result.get("error"), duration_ms)
            except Exception:
                logger.warning("Could not log tool call %s (conversation=%s)", name, cid)

        task = asyncio.create_task(asyncio.to_thread(log))
        _background.add(task)
        task.add_done_callback(_background.discard)
    return result
