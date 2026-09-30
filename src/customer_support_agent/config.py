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
    log_file: Path | None = None  # optional copy of the log, for local testing

    def __repr__(self) -> str:  # keep the token out of logs and tracebacks
        return (
            f"Settings(kb_path={self.kb_path!s}, retrieval_log_path={self.retrieval_log_path!s}, "
            f"mcp_host={self.mcp_host}, mcp_port={self.mcp_port}, mcp_auth_token=***, log_level={self.log_level})"
        )


def _port_named(value: str, name: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got '{value}'") from None
    if not 1 <= port <= 65535:
        raise ConfigError(f"{name} must be between 1 and 65535, got {port}")
    return port


def _port(value: str) -> int:
    return _port_named(value, "MCP_PORT")


def _mcp_token(env: Mapping[str, str]) -> str:
    token = env.get("MCP_AUTH_TOKEN", "")
    if not token:
        raise ConfigError("MCP_AUTH_TOKEN is not set (see .env.example)")
    if len(token) < MIN_TOKEN_LENGTH:
        raise ConfigError(f"MCP_AUTH_TOKEN must be at least {MIN_TOKEN_LENGTH} characters")
    return token


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name, str(default))
    try:
        number = int(value)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got '{value}'") from None
    if number < 1:
        raise ConfigError(f"{name} must be at least 1, got {number}")
    return number


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Settings for the MCP server."""
    env = os.environ if env is None else env
    token = _mcp_token(env)

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


@dataclass(frozen=True)
class AgentSettings:
    anthropic_api_key: str
    model: str
    max_turns: int
    turn_timeout_seconds: int
    session_idle_seconds: int
    max_sessions: int
    mcp_url: str
    mcp_auth_token: str

    def __repr__(self) -> str:  # keep both secrets out of logs and tracebacks
        return (
            f"AgentSettings(model={self.model}, max_turns={self.max_turns}, "
            f"turn_timeout_seconds={self.turn_timeout_seconds}, session_idle_seconds={self.session_idle_seconds}, "
            f"max_sessions={self.max_sessions}, mcp_url={self.mcp_url}, anthropic_api_key=***, mcp_auth_token=***)"
        )


_LOOPBACK = ("127.0.0.1", "localhost", "::1")


@dataclass(frozen=True)
class BackendSettings:
    host: str  # public listener; 127.0.0.1 locally (ngrok connects locally), 0.0.0.0 on Cloud Run
    port: int
    vapi_llm_secret: str
    log_level: str

    def __repr__(self) -> str:
        return f"BackendSettings(host={self.host}, port={self.port}, vapi_llm_secret=***, log_level={self.log_level})"


def load_backend_settings(env: Mapping[str, str] | None = None) -> BackendSettings:
    """Settings for the public app. Also enforces that the MCP server stays private."""
    env = os.environ if env is None else env

    secret = env.get("VAPI_LLM_SECRET", "")
    if len(secret) < MIN_TOKEN_LENGTH:
        raise ConfigError(f"VAPI_LLM_SECRET must be set and at least {MIN_TOKEN_LENGTH} characters")
    mcp_host = env.get("MCP_HOST", "127.0.0.1")
    if mcp_host not in _LOOPBACK:
        raise ConfigError(f"MCP_HOST must be a localhost address so the MCP server is never public, got '{mcp_host}'")
    port = _port_named(env.get("PORT", "8000"), "PORT")
    if port == _port(env.get("MCP_PORT", "8001")):
        raise ConfigError("PORT and MCP_PORT must be different")

    return BackendSettings(
        host=env.get("HOST", "127.0.0.1"),
        port=port,
        vapi_llm_secret=secret,
        log_level=load_settings(env).log_level,
    )


def load_agent_settings(env: Mapping[str, str] | None = None) -> AgentSettings:
    """Settings for the Agent SDK sessions. Kept separate so the MCP server doesn't need an Anthropic key."""
    env = os.environ if env is None else env

    api_key = env.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ConfigError("ANTHROPIC_API_KEY is not set (see .env.example)")

    host = env.get("MCP_HOST", "127.0.0.1")
    port = _port(env.get("MCP_PORT", "8001"))
    return AgentSettings(
        anthropic_api_key=api_key,
        model=env.get("AGENT_MODEL", "claude-haiku-4-5-20251001"),
        max_turns=_positive_int(env, "AGENT_MAX_TURNS", 6),
        turn_timeout_seconds=_positive_int(env, "AGENT_TURN_TIMEOUT_SECONDS", 15),  # under Vapi's 20 s
        session_idle_seconds=_positive_int(env, "AGENT_SESSION_IDLE_SECONDS", 180),
        max_sessions=_positive_int(env, "AGENT_MAX_SESSIONS", 10),
        mcp_url=f"http://{host}:{port}/mcp",
        mcp_auth_token=_mcp_token(env),
    )



def load_database_url(env: Mapping[str, str] | None = None) -> str:
    """The Supabase session-pooler connection string. The value is never put in an error message."""
    env = os.environ if env is None else env
    url = env.get("DATABASE_URL", "").strip()
    if not url:
        raise ConfigError("DATABASE_URL is not set (Supabase -> Connect -> Session pooler; see .env.example)")
    if not url.startswith(("postgresql://", "postgres://")):
        raise ConfigError("DATABASE_URL must start with postgresql://")
    if "[YOUR-PASSWORD]" in url or "<password>" in url:
        raise ConfigError("DATABASE_URL still has the password placeholder in it")
    return url
