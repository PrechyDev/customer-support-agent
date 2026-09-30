"""Run the MCP server on its own: `poetry run relaypay-mcp` (or `python -m customer_support_agent.mcp_server`).

The backend will later start this same app inside its own process. Running it
standalone is for local testing, the MCP Inspector, and graders.
"""

import logging
import sys

import uvicorn
from dotenv import load_dotenv

from customer_support_agent.config import ConfigError, load_settings
from customer_support_agent.kb import KnowledgeBase, KnowledgeBaseError
from customer_support_agent.logging_setup import configure_logging
from customer_support_agent.mcp_server.retrieval_log import JsonlRetrievalLogStore
from customer_support_agent.mcp_server.server import create_app

logger = logging.getLogger(__name__)

EXIT_CONFIG_ERROR = 2
EXIT_STARTUP_ERROR = 1


def main() -> int:
    load_dotenv()  # reads .env at the repo root; real env vars win
    configure_logging()

    try:
        settings = load_settings()
    except ConfigError as exc:
        logger.error("MCP server not started: %s", exc)
        return EXIT_CONFIG_ERROR
    configure_logging(settings.log_level, settings.log_file)

    try:
        kb = KnowledgeBase.from_file(settings.kb_path)
    except KnowledgeBaseError as exc:
        logger.error("MCP server not started: %s", exc)
        return EXIT_STARTUP_ERROR

    app = create_app(
        kb=kb,
        log_store=JsonlRetrievalLogStore(settings.retrieval_log_path),
        token=settings.mcp_auth_token,
        host=settings.mcp_host,
    )
    logger.info("MCP server '%s' listening on http://%s:%d/mcp", "relaypay", settings.mcp_host, settings.mcp_port)
    uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port, log_config=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
