"""Stop hook: a follow-up Bex promises must have a record behind it (SPECS §6).

In a test call Bex said "Lovely, a specialist will email you" without ever calling create_escalation, so
nobody would have followed up. The prompt says never to claim an action a tool didn't confirm; this makes
it hold in code. The Claude Agent SDK runs a Stop hook when the agent is about to finish its turn; returning
decision "block" makes it continue with our reason (docs: code.claude.com/docs/en/hooks, "Stop").

Blocks only when the reply promises a follow-up AND the call has no escalation, and only once per turn
(stop_hook_active): the second time it lets the turn end and logs an event for staff, so it can never loop.

The same hook catches a reply written without <say> tags (6 of 40 replies in the first eval run, 01-10):
nothing outside the tags is spoken, so the caller would only hear "could you say that again?". It asks the
model once to write the reply inside the tags; the untagged text itself is never spoken, because untagged
text is where Haiku's reasoning leaked in a real call.
"""

import asyncio
import logging
import re
from collections.abc import Callable
from typing import Any

from customer_support_agent.db.repository import RepositoryUnavailable

logger = logging.getLogger(__name__)

PROMISE = re.compile(
    r"\b(?:specialist|team|someone|they)\s*(?:will|'ll|is going to|are going to)\s+"
    r"(?:email|call|contact|reach out|reach|follow up|get back|get in touch|be in touch|ring)\b",
    re.IGNORECASE,
)

BLOCK_REASON = (
    "You told the caller a specialist will follow up, but no escalation exists for this call yet, so nobody "
    "would. Call create_escalation now (the contact comes from the pre-call form or the account; pass the "
    "reference if there is one). You've already told the caller, so after the tool call reply with only "
    '<say type="escalate"></say>.'
)


UNTAGGED_REASON = (
    "Your reply wasn't inside <say> tags, so the caller heard nothing. Write your reply to the caller again, "
    'inside <say type="..."></say>. Do not repeat tool calls you have already made.'
)


def promises_follow_up(text: str) -> bool:
    return bool(PROMISE.search(text or ""))


def make_stop_hook(repo: Any, conversation_id: str, spoken_now: Callable[[], str]) -> Callable:
    """The Stop hook for one call. spoken_now() gives what Bex has said this turn (a fallback for the
    hook's own last_assistant_message field)."""

    async def guard(input_data: dict, tool_use_id: str | None, context: Any) -> dict:
        last, said = input_data.get("last_assistant_message") or "", spoken_now()
        promised = await promise_check(input_data, f"{last} {said}")
        if promised or input_data.get("stop_hook_active"):
            return promised
        if last.strip() and not said.strip() and "<say" not in last and "<end_call" not in last:
            logger.warning("Reply had no <say> tags: asking the agent to write it again (conversation=%s)",
                           conversation_id)
            return {"decision": "block", "reason": UNTAGGED_REASON}
        return {}

    async def promise_check(input_data: dict, text: str) -> dict:
        if repo is None or not promises_follow_up(text):
            return {}
        try:
            escalated = bool(await asyncio.to_thread(repo.escalations, conversation_id))
        except RepositoryUnavailable:
            logger.warning("Promise check skipped: database unavailable (conversation=%s)", conversation_id)
            return {}
        if escalated:
            return {}
        if input_data.get("stop_hook_active"):  # already asked once this turn: never loop
            logger.warning("Follow-up promised but no escalation was created (conversation=%s)", conversation_id)
            try:
                await asyncio.to_thread(repo.log_event, conversation_id, "other",
                                        "Bex promised a specialist follow-up but no escalation was created",
                                        {"source": "promise_guard"})
            except RepositoryUnavailable:
                logger.warning("Could not log the missing escalation (conversation=%s)", conversation_id)
            return {}
        logger.warning("Follow-up promised without an escalation: asking the agent to create it (conversation=%s)",
                       conversation_id)
        return {"decision": "block", "reason": BLOCK_REASON}

    return guard
