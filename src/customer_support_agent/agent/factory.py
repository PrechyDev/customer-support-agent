"""Creates the real, started agent session for a call. The backend passes this to SessionManager."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from claude_agent_sdk import ClaudeSDKClient

from customer_support_agent.agent.options import build_options
from customer_support_agent.agent.prompt import build_system_prompt
from customer_support_agent.agent.session import AgentSession
from customer_support_agent.agent.sessions import SessionFactory
from customer_support_agent.config import AgentSettings
from customer_support_agent.kb import KnowledgeBase


def make_session_factory(settings: AgentSettings, kb: KnowledgeBase, workdir: Path | None = None) -> SessionFactory:
    workdir = workdir or Path(tempfile.gettempdir()) / "relaypay-agent"
    workdir.mkdir(parents=True, exist_ok=True)  # an empty folder for the engine, not the repo

    async def create(conversation_id: str) -> AgentSession:
        prompt = build_system_prompt(kb, datetime.now(UTC))  # built per call, so the date is current
        client = ClaudeSDKClient(options=build_options(settings, prompt, conversation_id, workdir))
        session = AgentSession(client, conversation_id, turn_timeout_seconds=settings.turn_timeout_seconds)
        await session.start()
        return session

    return create
