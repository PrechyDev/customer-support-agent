from pathlib import Path

import pytest

from customer_support_agent.config import ConfigError, load_settings

VALID_TOKEN = "x" * 32


def env(**overrides):
    base = {"MCP_AUTH_TOKEN": VALID_TOKEN}
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def test_defaults_when_only_token_is_set():
    settings = load_settings(env())
    assert settings.kb_path == Path("data/relaypay-knowledge-base.md")
    assert settings.retrieval_log_path == Path("logs/retrieval.jsonl")
    assert settings.mcp_host == "127.0.0.1"
    assert settings.mcp_port == 8001
    assert settings.log_level == "INFO"


def test_values_are_read_from_env():
    settings = load_settings(env(KB_PATH="other.md", MCP_PORT="9000", LOG_LEVEL="debug"))
    assert settings.kb_path == Path("other.md")
    assert settings.mcp_port == 9000
    assert settings.log_level == "DEBUG"


def test_missing_token_raises():
    with pytest.raises(ConfigError, match="MCP_AUTH_TOKEN"):
        load_settings(env(MCP_AUTH_TOKEN=None))


def test_short_token_raises():
    with pytest.raises(ConfigError, match="at least 32"):
        load_settings(env(MCP_AUTH_TOKEN="short"))


@pytest.mark.parametrize("port", ["abc", "0", "70000"])
def test_invalid_port_raises(port):
    with pytest.raises(ConfigError, match="MCP_PORT"):
        load_settings(env(MCP_PORT=port))


def test_invalid_log_level_raises():
    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        load_settings(env(LOG_LEVEL="LOUD"))


def test_error_message_never_contains_the_token():
    with pytest.raises(ConfigError) as exc:
        load_settings(env(MCP_AUTH_TOKEN="secret-but-too-short"))
    assert "secret-but-too-short" not in str(exc.value)
