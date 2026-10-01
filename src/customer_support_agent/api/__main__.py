"""Start everything with one command: `poetry run relaypay-backend`.

Loads the KB once, starts the MCP server on localhost, waits until it's up, then starts
the public app. If either stops, the other stops too.
"""

import asyncio
import contextlib
import logging
import sys
from datetime import UTC, datetime

import uvicorn
from dotenv import load_dotenv
from starlette.types import ASGIApp

from customer_support_agent.agent.factory import make_session_factory
from customer_support_agent.agent.sessions import SessionManager
from customer_support_agent.api.app import create_app
from customer_support_agent.api.records import CallRecorder
from customer_support_agent.config import (
    ConfigError,
    load_agent_settings,
    load_backend_settings,
    load_database_schema,
    load_database_url,
    load_settings,
    load_voice_settings,
)
from customer_support_agent.db.repository import Repository
from customer_support_agent.kb import KnowledgeBase, KnowledgeBaseError
from customer_support_agent.logging_setup import configure_logging
from customer_support_agent.mcp_server.retrieval_log import BackgroundLogStore, SupabaseRetrievalLogStore
from customer_support_agent.mcp_server.tools import cases
from customer_support_agent.mcp_server.tools.common import run_tool
from customer_support_agent.mcp_server.server import create_app as create_mcp_app

logger = logging.getLogger(__name__)

EXIT_CONFIG_ERROR = 2
STUCK_REASON = "The agent couldn't complete the caller's request twice in a row."
EXIT_STARTUP_ERROR = 1


def main() -> int:
    load_dotenv()  # .env at the repo root; real env vars win
    configure_logging()
    try:
        mcp_settings = load_settings()
        agent_settings = load_agent_settings()
        backend = load_backend_settings()
        database_url = load_database_url()  # the backend keeps records of every call, so it's required
        schema = load_database_schema()
        voice = load_voice_settings()  # optional: the voice page needs them to start calls
    except ConfigError as exc:
        logger.error("Backend not started: %s", exc)
        return EXIT_CONFIG_ERROR
    configure_logging(mcp_settings.log_level, mcp_settings.log_file)

    try:
        kb = KnowledgeBase.from_file(mcp_settings.kb_path)
    except KnowledgeBaseError as exc:
        logger.error("Backend not started: %s", exc)
        return EXIT_STARTUP_ERROR

    repo = Repository(database_url, schema)
    repo.open()  # connects in the background; a database that's down only makes the tools say "unavailable"
    mcp_app = create_mcp_app(kb=kb, log_store=BackgroundLogStore(SupabaseRetrievalLogStore(repo)),
                             token=mcp_settings.mcp_auth_token, host=mcp_settings.mcp_host, repo=repo)
    recorder = CallRecorder(repo, model=agent_settings.model)

    async def escalate_stuck(cid: str) -> bool:
        """The agent couldn't finish the caller's request twice: hand the call to a specialist. Only works
        if we know who to follow up with (verified record or pre-call form); otherwise False."""
        result = await run_tool(repo, cid, "create_escalation", "automatic: agent stuck twice", "other",
                                lambda: cases.create_escalation(repo, cid, "other", STUCK_REASON, datetime.now(UTC)),
                                exclusive=True)
        return "escalation_id" in result

    manager = SessionManager(make_session_factory(agent_settings, kb), max_sessions=agent_settings.max_sessions,
                             idle_seconds=agent_settings.session_idle_seconds,
                             wait_seconds=agent_settings.turn_timeout_seconds, on_idle_close=recorder.abandoned,
                             on_stuck=escalate_stuck)
    app = create_app(manager, vapi_secret=backend.vapi_llm_secret, recorder=recorder, voice=voice,
                     repo=repo)
    if not (voice.public_key and voice.assistant_id):
        logger.warning("VAPI_PUBLIC_KEY / VAPI_ASSISTANT_ID not set: the voice page can't start calls")

    logger.info("Agent model: %s; database schema: %s", agent_settings.model, schema)
    try:
        return asyncio.run(_serve(app, mcp_app, backend.host, backend.port, mcp_settings.mcp_host, mcp_settings.mcp_port))
    except KeyboardInterrupt:  # Ctrl+C: both servers have already shut down cleanly
        logger.info("Backend stopped")
        return 0
    finally:
        repo.close()


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
