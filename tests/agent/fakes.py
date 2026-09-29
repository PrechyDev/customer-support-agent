"""A stand-in for the SDK client, so agent tests never call Claude."""

import asyncio

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from claude_agent_sdk.types import StreamEvent


def delta(text: str) -> StreamEvent:
    return StreamEvent(uuid="u", session_id="s", event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}})


def assistant(*blocks) -> AssistantMessage:
    return AssistantMessage(content=list(blocks), model="test-model")


def text(value: str) -> TextBlock:
    return TextBlock(text=value)


def tool_use(name: str) -> ToolUseBlock:
    return ToolUseBlock(id="t1", name=name, input={"query": "fees"})


def result(subtype: str = "success", is_error: bool = False, num_turns: int = 2, cost: float = 0.0012) -> ResultMessage:
    return ResultMessage(subtype=subtype, duration_ms=900, duration_api_ms=800, is_error=is_error,
                         num_turns=num_turns, session_id="s", total_cost_usd=cost)


class FakeClient:
    """Replays a scripted list of messages for each query."""

    def __init__(self, scripts=(), *, connect_error=None, query_error=None, hang=False):
        self.scripts = list(scripts)
        self.connect_error = connect_error
        self.query_error = query_error
        self.hang = hang
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
        for message in self.scripts.pop(0):
            yield message

    async def interrupt(self):
        self.interrupted = True

    async def disconnect(self):
        self.disconnected = True
