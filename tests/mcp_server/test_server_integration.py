"""End to end: run the real MCP app over HTTP and talk to it with the official MCP client."""

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
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class MemoryLogStore:
    def __init__(self) -> None:
        self.records = []

    def record(self, record) -> None:
        self.records.append(record)


@pytest.fixture(scope="module")
def server():
    store = MemoryLogStore()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = create_app(kb=KnowledgeBase.from_file(KB_PATH), log_store=store, token=TOKEN)
    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not uv.started:
        if time.time() > deadline:
            raise RuntimeError("MCP test server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp", store
    uv.should_exit = True
    thread.join(timeout=5)


async def session(url, headers, work):
    async with httpx2.AsyncClient(headers=headers, timeout=10) as http:
        async with Client(streamable_http_client(url, http_client=http)) as client:
            return await work(client)


def test_authorized_client_lists_and_calls_the_tool(server):
    url, store = server

    async def work(client):
        tools = await client.list_tools()
        result = await client.call_tool("search_knowledge_base", {"query": "fees international payments"})
        return tools, result

    tools, result = asyncio.run(session(url, {**AUTH, "X-Conversation-Id": "call-abc"}, work))
    assert [t.name for t in tools.tools] == ["search_knowledge_base"]
    assert result.structured_content["results"][0]["chunk_id"] == "how-does-relaypay-charge-fees"
    assert store.records[-1].conversation_id == "call-abc"

    asyncio.run(session(url, AUTH, lambda c: c.call_tool("search_knowledge_base", {"query": "exchange rates"})))
    assert store.records[-1].conversation_id == "unknown"  # header missing


def test_unauthorized_requests_are_refused(server):
    url, _ = server
    assert httpx2.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401
    with pytest.raises(Exception):
        asyncio.run(session(url, {"Authorization": "Bearer " + "w" * 32}, lambda c: c.list_tools()))
