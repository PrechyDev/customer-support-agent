"""Settings read from environment variables, validated once at startup.

`.env` is loaded by the entry points (python-dotenv), not here, so this module
stays easy to test with a plain dict.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

MIN_TOKEN_LENGTH = 32
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ConfigError(Exception):
    """A required setting is missing or invalid. Messages never include secret values."""


@dataclass(frozen=True)
class Settings:
    kb_path: Path
    retrieval_log_path: Path
    mcp_host: str
    mcp_port: int
    mcp_auth_token: str
    log_level: str

    def __repr__(self) -> str:  # keep the token out of logs and tracebacks
        return (
            f"Settings(kb_path={self.kb_path!s}, retrieval_log_path={self.retrieval_log_path!s}, "
            f"mcp_host={self.mcp_host}, mcp_port={self.mcp_port}, mcp_auth_token=***, log_level={self.log_level})"
        )


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise ConfigError(f"MCP_PORT must be a number, got '{value}'") from None
    if not 1 <= port <= 65535:
        raise ConfigError(f"MCP_PORT must be between 1 and 65535, got {port}")
    return port


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env

    token = env.get("MCP_AUTH_TOKEN", "")
    if not token:
        raise ConfigError("MCP_AUTH_TOKEN is not set (see .env.example)")
    if len(token) < MIN_TOKEN_LENGTH:
        raise ConfigError(f"MCP_AUTH_TOKEN must be at least {MIN_TOKEN_LENGTH} characters")

    log_level = env.get("LOG_LEVEL", "INFO").upper()
    if log_level not in _LOG_LEVELS:
        raise ConfigError(f"LOG_LEVEL must be one of {', '.join(_LOG_LEVELS)}, got '{log_level}'")

    return Settings(
        kb_path=Path(env.get("KB_PATH", "data/relaypay-knowledge-base.md")),
        retrieval_log_path=Path(env.get("RETRIEVAL_LOG_PATH", "logs/retrieval.jsonl")),
        mcp_host=env.get("MCP_HOST", "127.0.0.1"),
        mcp_port=_port(env.get("MCP_PORT", "8001")),
        mcp_auth_token=token,
        log_level=log_level,
    )
