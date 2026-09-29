import pytest

from customer_support_agent.mcp_server import __main__ as entry


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    # Never read the developer's real .env during tests.
    monkeypatch.setattr(entry, "load_dotenv", lambda *a, **k: False)


@pytest.fixture
def started(monkeypatch):
    calls = []
    monkeypatch.setattr(entry.uvicorn, "run", lambda app, **kw: calls.append(kw))
    return calls


def test_missing_token_exits_with_config_error(monkeypatch, started, caplog):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    assert entry.main() == entry.EXIT_CONFIG_ERROR
    assert "MCP_AUTH_TOKEN" in caplog.text
    assert started == []


def test_missing_kb_exits_with_startup_error(monkeypatch, started, tmp_path, caplog):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "k" * 32)
    monkeypatch.setenv("KB_PATH", str(tmp_path / "missing.md"))
    assert entry.main() == entry.EXIT_STARTUP_ERROR
    assert "not found" in caplog.text
    assert started == []


def test_valid_settings_start_server_on_localhost(monkeypatch, started, tmp_path):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "k" * 32)
    monkeypatch.setenv("RETRIEVAL_LOG_PATH", str(tmp_path / "r.jsonl"))
    monkeypatch.delenv("KB_PATH", raising=False)
    monkeypatch.delenv("MCP_HOST", raising=False)
    assert entry.main() == 0
    assert started == [{"host": "127.0.0.1", "port": 8001, "log_config": None}]
