"""Creates the real, started agent session for a call. The backend passes this to SessionManager."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from claude_agent_sdk import ClaudeSDKClient

from customer_support_agent.agent.options import build_options
from customer_support_agent.agent.prompt import build_system_prompt
from customer_support_agent.agent.session import AgentSession
from customer_support_agent.agent.sessions import Caller, SessionFactory
from customer_support_agent.config import AgentSettings
from customer_support_agent.kb import KnowledgeBase


def make_session_factory(settings: AgentSettings, kb: KnowledgeBase, workdir: Path | None = None) -> SessionFactory:
    workdir = workdir or Path(tempfile.gettempdir()) / "relaypay-agent"
    (workdir / "claude-config").mkdir(parents=True, exist_ok=True)  # engine config + transcripts, not ~/.claude

    async def create(conversation_id: str, caller: Caller | None = None) -> AgentSession:
        prompt = build_system_prompt(kb, datetime.now(UTC), caller)  # per call: current date, this caller's form
        client = ClaudeSDKClient(options=build_options(settings, prompt, conversation_id, workdir))
        session = AgentSession(client, conversation_id, turn_timeout_seconds=settings.turn_timeout_seconds)
        await session.start()
        return session

    return create
