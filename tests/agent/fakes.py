"""A stand-in for the SDK client, so agent tests never call Claude.

Like the real engine, it has ONE continuous output stream shared by all turns: each
receive_response() reads until the next ResultMessage. So if a turn stops reading early and
nothing drains the rest, the next turn reads the leftovers (the bug this fake now reproduces).
"""

import asyncio
from collections import deque

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage
from claude_agent_sdk.types import StreamEvent

KB_TOOL = "mcp__relaypay__search_knowledge_base"


def _event(event: dict) -> StreamEvent:
    return StreamEvent(uuid="u", session_id="s", event=event)


def reply(text: str | None = None, tool: str | None = None, pieces: int = 2, say: bool = True) -> list:
    """One model message as the real stream sends it: start, text deltas, optional tool call, stop,
    then the full AssistantMessage record. Text is wrapped in <say> tags unless say=False."""
    if text and say and not tool:
        text = f"<say>{text}</say>"
    out = [_event({"type": "message_start", "message": {"id": "m"}})]
    if text:
        out.append(_event({"type": "content_block_start", "content_block": {"type": "text"}}))
        size = max(1, len(text) // pieces)
        for i in range(0, len(text), size):
            out.append(_event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": text[i:i + size]}}))
    if tool:
        out.append(_event({"type": "content_block_start", "content_block": {"type": "tool_use", "name": tool}}))
    out.append(_event({"type": "message_stop"}))
    blocks = ([TextBlock(text=text)] if text else []) + ([ToolUseBlock(id="t1", name=tool, input={})] if tool else [])
    out.append(AssistantMessage(content=blocks, model="test-model"))
    return out


def assistant_only(text: str | None = None, tool: str | None = None) -> AssistantMessage:
    """A full message with no stream events (partial streaming off)."""
    if text and not tool:
        text = f"<say>{text}</say>"
    blocks = ([TextBlock(text=text)] if text else []) + ([ToolUseBlock(id="t1", name=tool, input={})] if tool else [])
    return AssistantMessage(content=blocks, model="test-model")


def tool_result(text: str) -> UserMessage:
    """What the engine passes back after a tool runs (MCP results arrive as text content)."""
    return UserMessage(content=[ToolResultBlock(tool_use_id="t1", content=[{"type": "text", "text": text}])])


def result(subtype: str = "success", is_error: bool = False, num_turns: int = 2, cost: float = 0.0012) -> ResultMessage:
    return ResultMessage(subtype=subtype, duration_ms=900, duration_api_ms=800, is_error=is_error,
                         num_turns=num_turns, session_id="s", total_cost_usd=cost)


class FakeClient:
    """Scripts are appended, in order, to one shared output stream."""

    def __init__(self, scripts=(), *, connect_error=None, query_error=None, hang=False, slow_seconds=0.0):
        self.stream = deque(item for script in scripts for item in script)
        self.connect_error = connect_error
        self.query_error = query_error
        self.hang = hang
        self.slow_seconds = slow_seconds  # pause between items, so a reader can stop mid-reply
        self.queries: list[str] = []
        self.connected = False
        self.disconnected = False
        self.interrupted = False

    async def connect(self):
        if self.connect_error:
            raise self.connect_error
        self.connected = True

    async def query(self, prompt: str):
        if self.query_error:
            raise self.query_error
        self.queries.append(prompt)

    async def receive_response(self):
        if self.hang:
            await asyncio.sleep(3600)
        while self.stream:
            item = self.stream.popleft()
            if self.slow_seconds:
                await asyncio.sleep(self.slow_seconds)
            yield item
            if isinstance(item, ResultMessage):
                return

    async def interrupt(self):
        self.interrupted = True

    async def disconnect(self):
        self.disconnected = True
