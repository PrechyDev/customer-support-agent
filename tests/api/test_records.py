"""Background call-record writes: one retry, then a loud ERROR if the record is lost."""

import asyncio
import logging

from customer_support_agent.api import records
from customer_support_agent.api.records import CallRecorder
from customer_support_agent.db.repository import RepositoryUnavailable
from tests.mcp_server.fake_repo import FakeRepository


class Flaky(FakeRepository):
    """Down for the first `failures` writes, then fine."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    def log_event(self, *args):
        if self.failures:
            self.failures -= 1
            raise RepositoryUnavailable("database down")
        return super().log_event(*args)


def record_event(repo) -> None:
    async def go():
        recorder = CallRecorder(repo)
        recorder.event("call-1", "note", "hello")
        await recorder.wait()
    asyncio.run(go())


def test_a_failed_write_is_retried_once_then_reported(monkeypatch, caplog):
    monkeypatch.setattr(records, "RETRY_SECONDS", 0)
    hiccup = Flaky(failures=1)
    record_event(hiccup)
    assert len(hiccup.events) == 1  # saved on the retry

    with caplog.at_level(logging.ERROR):
        record_event(Flaky(failures=2))
    assert "Lost a call record (event)" in caplog.text
