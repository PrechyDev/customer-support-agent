"""Start everything with one command: `poetry run relaypay-backend`.

Loads the KB once, starts the MCP server on localhost, waits until it's up, then starts
the public app. If either stops, the other stops too.
"""

import asyncio
import contextlib
import logging
import sys

import uvicorn
from dotenv import load_dotenv
from starlette.types import ASGIApp

from customer_support_agent.agent.factory import make_session_factory
from customer_support_agent.agent.sessions import SessionManager
from customer_support_agent.api.app import create_app
from customer_support_agent.config import (
    ConfigError,
    load_agent_settings,
    load_backend_settings,
    load_settings,
)
from customer_support_agent.kb import KnowledgeBase, KnowledgeBaseError
from customer_support_agent.logging_setup import configure_logging
from customer_support_agent.mcp_server.retrieval_log import JsonlRetrievalLogStore
from customer_support_agent.mcp_server.server import create_app as create_mcp_app

logger = logging.getLogger(__name__)

EXIT_CONFIG_ERROR = 2
EXIT_STARTUP_ERROR = 1


def main() -> int:
    load_dotenv()  # .env at the repo root; real env vars win
    configure_logging()
    try:
        mcp_settings = load_settings()
        agent_settings = load_agent_settings()
        backend = load_backend_settings()
    except ConfigError as exc:
        logger.error("Backend not started: %s", exc)
        return EXIT_CONFIG_ERROR
    configure_logging(mcp_settings.log_level)

    try:
        kb = KnowledgeBase.from_file(mcp_settings.kb_path)
    except KnowledgeBaseError as exc:
        logger.error("Backend not started: %s", exc)
        return EXIT_STARTUP_ERROR

    mcp_app = create_mcp_app(kb=kb, log_store=JsonlRetrievalLogStore(mcp_settings.retrieval_log_path),
                             token=mcp_settings.mcp_auth_token, host=mcp_settings.mcp_host)
    manager = SessionManager(make_session_factory(agent_settings, kb), max_sessions=agent_settings.max_sessions,
                             idle_seconds=agent_settings.session_idle_seconds)
    app = create_app(manager, vapi_secret=backend.vapi_llm_secret)

    logger.info("Agent model: %s", agent_settings.model)
    try:
        return asyncio.run(_serve(app, mcp_app, backend.host, backend.port, mcp_settings.mcp_host, mcp_settings.mcp_port))
    except KeyboardInterrupt:  # Ctrl+C: both servers have already shut down cleanly
        logger.info("Backend stopped")
        return 0


async def _serve(app: ASGIApp, mcp_app: ASGIApp, host: str, port: int, mcp_host: str, mcp_port: int) -> int:
    mcp = uvicorn.Server(uvicorn.Config(mcp_app, host=mcp_host, port=mcp_port, log_config=None))
    public = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_config=None))

    mcp_task = asyncio.create_task(mcp.serve())
    while not mcp.started:  # the agent needs MCP before the first call
        if mcp_task.done():
            logger.error("MCP server failed to start on %s:%d", mcp_host, mcp_port)
            return EXIT_STARTUP_ERROR
        await asyncio.sleep(0.05)
    logger.info("MCP server ready on http://%s:%d/mcp (localhost only)", mcp_host, mcp_port)

    try:
        await public.serve()
    finally:
        mcp.should_exit = True
        with contextlib.suppress(asyncio.CancelledError):  # Ctrl+C cancels it; that's a normal stop
            await mcp_task
    return 0


if __name__ == "__main__":
    sys.exit(main())
