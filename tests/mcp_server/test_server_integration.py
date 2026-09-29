"""End to end: run the real MCP app over HTTP and talk to it with the MCP client."""

import asyncio
import socket
import threading
import time
from pathlib import Path

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from customer_support_agent.kb import KnowledgeBase
from customer_support_agent.mcp_server.server import create_app

KB_PATH = Path(__file__).parents[2] / "data" / "relaypay-knowledge-base.md"
TOKEN = "i" * 32


class MemoryLogStore:
    def __init__(self) -> None:
        self.records = []

    def record(self, record) -> None:
        self.records.append(record)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def running_server():
    store = MemoryLogStore()
    app = create_app(kb=KnowledgeBase.from_file(KB_PATH), log_store=store, token=TOKEN)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("MCP test server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp", store
    server.should_exit = True
    thread.join(timeout=5)


async def call(url, headers, tool=None, args=None):
    async with httpx2.AsyncClient(headers=headers, timeout=10) as http:
        async with Client(streamable_http_client(url, http_client=http)) as client:
            if tool is None:
                return await client.list_tools()
            return await client.call_tool(tool, args or {})


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_tool_is_listed(running_server):
    url, _ = running_server
    tools = asyncio.run(call(url, AUTH))
    assert [t.name for t in tools.tools] == ["search_knowledge_base"]


def test_search_over_http_returns_chunks_and_logs_conversation_id(running_server):
    url, store = running_server
    headers = {**AUTH, "X-Conversation-Id": "call-abc"}
    result = asyncio.run(call(url, headers, "search_knowledge_base", {"query": "fees international payments"}))

    assert result.is_error is False
    data = result.structured_content
    assert data["found"] is True
    assert data["results"][0]["chunk_id"] == "how-does-relaypay-charge-fees"
    assert store.records[-1].conversation_id == "call-abc"


def test_missing_conversation_id_is_logged_as_unknown(running_server):
    url, store = running_server
    asyncio.run(call(url, AUTH, "search_knowledge_base", {"query": "exchange rates"}))
    assert store.records[-1].conversation_id == "unknown"


def test_request_without_token_is_rejected(running_server):
    url, _ = running_server
    response = httpx2.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401


def test_client_with_wrong_token_cannot_connect(running_server):
    url, _ = running_server
    with pytest.raises(Exception):
        asyncio.run(call(url, {"Authorization": "Bearer " + "w" * 32}))
