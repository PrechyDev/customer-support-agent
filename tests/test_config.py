from pathlib import Path

import pytest

from customer_support_agent.config import ConfigError, load_agent_settings, load_backend_settings, load_settings

TOKEN = "x" * 32
BASE = {"MCP_AUTH_TOKEN": TOKEN}
AGENT = {**BASE, "ANTHROPIC_API_KEY": "sk-test"}


def test_mcp_defaults():
    s = load_settings(BASE)
    assert (s.kb_path, s.mcp_host, s.mcp_port, s.log_level) == (
        Path("data/relaypay-knowledge-base.md"), "127.0.0.1", 8001, "INFO")


def test_missing_or_short_token_raises_without_leaking_it():
    with pytest.raises(ConfigError, match="MCP_AUTH_TOKEN"):
        load_settings({})
    with pytest.raises(ConfigError, match="at least 32") as exc:
        load_settings({"MCP_AUTH_TOKEN": "secret-but-short"})
    assert "secret-but-short" not in str(exc.value)


def test_invalid_port_and_log_level_raise():
    with pytest.raises(ConfigError, match="MCP_PORT"):
        load_settings({**BASE, "MCP_PORT": "70000"})
    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        load_settings({**BASE, "LOG_LEVEL": "LOUD"})


def test_agent_defaults_and_mcp_url():
    s = load_agent_settings({**AGENT, "MCP_PORT": "9001"})
    assert (s.model, s.max_turns, s.turn_timeout_seconds, s.session_idle_seconds, s.max_sessions) == (
        "claude-haiku-4-5-20251001", 6, 30, 180, 10)
    assert s.mcp_url == "http://127.0.0.1:9001/mcp"


def test_agent_requires_key_and_valid_numbers():
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        load_agent_settings(BASE)
    with pytest.raises(ConfigError, match="AGENT_MAX_TURNS"):
        load_agent_settings({**AGENT, "AGENT_MAX_TURNS": "0"})


def test_backend_settings_protect_the_mcp_server():
    ok = {**AGENT, "VAPI_LLM_SECRET": "v" * 32}
    s = load_backend_settings(ok)
    assert (s.host, s.port) == ("127.0.0.1", 8000)
    for bad, field in (({"VAPI_LLM_SECRET": "short"}, "VAPI_LLM_SECRET"),
                       ({"MCP_HOST": "0.0.0.0"}, "MCP_HOST"),
                       ({"PORT": "8001"}, "PORT")):
        with pytest.raises(ConfigError, match=field):
            load_backend_settings({**ok, **bad})


def test_repr_hides_secrets():
    text = repr(load_settings(BASE)) + repr(load_agent_settings(AGENT))
    assert TOKEN not in text and "sk-test" not in text
