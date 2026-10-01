import asyncio
from pathlib import Path

from customer_support_agent.agent import factory as factory_module
from customer_support_agent.agent.factory import make_session_factory
from customer_support_agent.config import load_agent_settings
from customer_support_agent.kb import KnowledgeBase

KB_PATH = Path(__file__).parents[2] / "data" / "relaypay-knowledge-base.md"


def test_factory_builds_a_started_session_with_locked_down_options(monkeypatch, tmp_path):
    created = []

    class RecordingClient:
        def __init__(self, options):
            self.options = options
            self.connected = False
            created.append(self)

        async def connect(self):
            self.connected = True

    monkeypatch.setattr(factory_module, "ClaudeSDKClient", RecordingClient)
    settings = load_agent_settings({"ANTHROPIC_API_KEY": "sk-test", "MCP_AUTH_TOKEN": "f" * 32})
    create = make_session_factory(settings, KnowledgeBase.from_file(KB_PATH), workdir=tmp_path / "agent")

    session = asyncio.run(create("call-9"))

    assert session.conversation_id == "call-9"
    client = created[0]
    assert client.connected is True
    assert client.options.mcp_servers["relaypay"]["headers"]["X-Conversation-Id"] == "call-9"
    assert "KNOWLEDGE BASE SECTIONS" in client.options.system_prompt
    assert list(client.options.hooks) == ["Stop"]  # the promised-follow-up guard is on every session
    assert (tmp_path / "agent" / "claude-config").is_dir()  # working folder + engine config folder created
