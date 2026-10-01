"""The MCP server: registers the tools and builds the HTTP app (SPECS §1, §9).

This is the only MCP-specific module. Tool logic lives in `tools/`.
Transport: Streamable HTTP, stateless, bound to localhost, behind a bearer token.
The conversation ID comes from the X-Conversation-Id header (set by the backend, never the model).
"""

import logging
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from starlette.types import ASGIApp

from customer_support_agent.kb import KnowledgeBase
from customer_support_agent.mcp_server.auth import BearerTokenMiddleware
from customer_support_agent.mcp_server.retrieval_log import RetrievalLogStore
from customer_support_agent.mcp_server.tools import accounts, cases, knowledge
from customer_support_agent.mcp_server.tools.common import run_tool
from customer_support_agent.domain.normalise import mask_email

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


def create_mcp_server(kb: KnowledgeBase, log_store: RetrievalLogStore, repo: Any = None,
                      now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> MCPServer:
    server = MCPServer(name=SERVER_NAME, instructions="RelayPay customer support tools.")

    def ready(ctx: Context) -> str:
        return conversation_id_from(ctx.headers)

    @server.tool(description=knowledge.DESCRIPTION)
    async def search_knowledge_base(query: str, ctx: Context) -> dict[str, Any]:
        return knowledge.search_knowledge_base(query, kb=kb, log_store=log_store, conversation_id=ready(ctx))

    @server.tool(description=accounts.LOOKUP_CUSTOMER)
    async def lookup_customer(ctx: Context, email: str | None = None, company_name: str | None = None) -> dict[str, Any]:
        cid = ready(ctx)
        return await run_tool(repo, cid, "lookup_customer", "verify caller", f"email={mask_email(email)} company={company_name}",
                              lambda: accounts.lookup_customer(repo, cid, email, company_name), exclusive=True)

    @server.tool(description=accounts.LOOKUP_TRANSACTION)
    async def lookup_transaction(transaction_id: str, ctx: Context) -> dict[str, Any]:
        cid = ready(ctx)
        return await run_tool(repo, cid, "lookup_transaction", "transaction status", f"ref={transaction_id}",
                              lambda: accounts.lookup_transaction(repo, cid, transaction_id, now().date()))

    @server.tool(description=accounts.LOOKUP_PAYOUT)
    async def lookup_payout(ctx: Context, payout_id: str | None = None, transaction_id: str | None = None) -> dict[str, Any]:
        cid = ready(ctx)
        return await run_tool(repo, cid, "lookup_payout", "payout status", f"payout={payout_id} txn={transaction_id}",
                              lambda: accounts.lookup_payout(repo, cid, payout_id, transaction_id, now().date()))

    @server.tool(description=cases.CREATE_TICKET)
    async def create_support_ticket(category: str, priority: str, summary: str, ctx: Context,
                                    reference: str | None = None) -> dict[str, Any]:
        cid = ready(ctx)
        return await run_tool(repo, cid, "create_support_ticket", "log a problem", f"{category}/{priority} ref={reference}",
                              lambda: cases.create_support_ticket(repo, cid, category, priority, summary, reference),
                              exclusive=True)

    @server.tool(description=cases.CREATE_ESCALATION)
    async def create_escalation(category: str, reason: str, ctx: Context, user_name: str | None = None,
                                user_email: str | None = None, callback_place: str | None = None,
                                callback_day: str | None = None, callback_time: str | None = None,
                                preferred_time: str | None = None, ticket_id: str | None = None) -> dict[str, Any]:
        cid = ready(ctx)
        summary = f"{category} email={mask_email(user_email)} callback={callback_day} {callback_time} {callback_place}"
        return await run_tool(repo, cid, "create_escalation", "hand to a specialist", summary,
                              lambda: cases.create_escalation(repo, cid, category, reason, now(), user_name, user_email,
                                                              callback_place, callback_day, callback_time,
                                                              preferred_time, ticket_id), exclusive=True)

    @server.tool(description=cases.LOG_EVENT)
    async def log_conversation_event(event_type: str, summary: str, ctx: Context,
                                     metadata: dict | None = None) -> dict[str, Any]:
        cid = ready(ctx)
        return await run_tool(repo, cid, "log_conversation_event", "record a judgement call", event_type,
                              lambda: cases.log_conversation_event(repo, cid, event_type, summary, metadata))

    return server


def create_app(kb: KnowledgeBase, log_store: RetrievalLogStore, token: str, host: str = "127.0.0.1",
               repo: Any = None) -> ASGIApp:
    mcp_app = create_mcp_server(kb, log_store, repo).streamable_http_app(stateless_http=True, json_response=True, host=host)
    return BearerTokenMiddleware(mcp_app, token=token)
