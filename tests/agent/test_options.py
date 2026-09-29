"""The lock-down settings. If someone loosens one later, a test here fails."""

from pathlib import Path

from customer_support_agent.agent.options import build_options
from customer_support_agent.config import load_agent_settings

TOKEN = "m" * 32


def make(tmp_path):
    settings = load_agent_settings({"ANTHROPIC_API_KEY": "sk-test", "MCP_AUTH_TOKEN": TOKEN, "AGENT_MODEL": "claude-sonnet-5"})
    return build_options(settings, system_prompt="PROMPT", conversation_id="call-7", workdir=tmp_path)


def test_agent_is_locked_down(tmp_path):
    o = make(tmp_path)
    assert o.tools == []  # no built-in file, shell or web tools
    assert o.allowed_tools == ["mcp__relaypay__search_knowledge_base"]
    assert o.permission_mode == "dontAsk"
    assert o.setting_sources == []  # no ~/.claude settings, hooks, plugins or CLAUDE.md
    assert o.strict_mcp_config is True  # no other MCP servers
    assert Path(o.cwd) == tmp_path  # not the repo


def test_agent_uses_our_prompt_model_and_mcp_server(tmp_path):
    o = make(tmp_path)
    assert (o.system_prompt, o.model, o.max_turns) == ("PROMPT", "claude-sonnet-5", 6)
    assert o.mcp_servers == {"relaypay": {
        "type": "http", "url": "http://127.0.0.1:8001/mcp",
        "headers": {"Authorization": f"Bearer {TOKEN}", "X-Conversation-Id": "call-7"},
    }}
    assert o.include_partial_messages is True and o.thinking == {"type": "disabled"}
    assert o.env == {"ANTHROPIC_API_KEY": "sk-test"}
