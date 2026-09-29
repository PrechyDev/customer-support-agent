"""The MCP server: registers the tools and builds the HTTP app (SPECS §1, §9).

This is the only MCP-specific module. Tool logic lives in `tools/`.
Transport: Streamable HTTP, stateless, bound to localhost, behind a bearer token.
"""

import logging
import re
from collections.abc import Mapping
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from starlette.types import ASGIApp

from customer_support_agent.kb import KnowledgeBase
from customer_support_agent.mcp_server.auth import BearerTokenMiddleware
from customer_support_agent.mcp_server.retrieval_log import RetrievalLogStore
from customer_support_agent.mcp_server.tools import knowledge

logger = logging.getLogger(__name__)

SERVER_NAME = "relaypay"
CONVERSATION_HEADER = "x-conversation-id"
_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def conversation_id_from(headers: Mapping[str, str] | None) -> str:
    """The backend sets X-Conversation-Id per call. The model never sees or sets it."""
    value = next((v for k, v in (headers or {}).items() if k.lower() == CONVERSATION_HEADER), None)
    if value is None:
        return "unknown"
    if not _CONVERSATION_ID.match(value):
        logger.warning("Ignoring malformed %s header", CONVERSATION_HEADER)
        return "unknown"
    return value


def create_mcp_server(kb: KnowledgeBase, log_store: RetrievalLogStore) -> MCPServer:
    server = MCPServer(name=SERVER_NAME, instructions="RelayPay customer support tools.")

    @server.tool(description=knowledge.DESCRIPTION)
    async def search_knowledge_base(query: str, ctx: Context) -> dict[str, Any]:
        return knowledge.search_knowledge_base(
            query, kb=kb, log_store=log_store, conversation_id=conversation_id_from(ctx.headers)
        )

    return server


def create_app(kb: KnowledgeBase, log_store: RetrievalLogStore, token: str, host: str = "127.0.0.1") -> ASGIApp:
    mcp_app = create_mcp_server(kb, log_store).streamable_http_app(stateless_http=True, json_response=True, host=host)
    return BearerTokenMiddleware(mcp_app, token=token)
