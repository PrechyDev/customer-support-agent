from pathlib import Path

import pytest

from customer_support_agent.kb import KnowledgeBase
from customer_support_agent.mcp_server.tools.knowledge import MAX_QUERY_LENGTH, search_knowledge_base

KB_PATH = Path(__file__).parents[2] / "data" / "relaypay-knowledge-base.md"


class FakeLogStore:
    def __init__(self, fail: bool = False) -> None:
        self.records = []
        self.fail = fail

    def record(self, record) -> None:
        if self.fail:
            raise OSError("disk full")
        self.records.append(record)


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase.from_file(KB_PATH)


def run(kb, query, store=None):
    return search_knowledge_base(query, kb=kb, log_store=store or FakeLogStore(), conversation_id="call-1")


def test_returns_chunks_or_a_decline_note(kb):
    found = run(kb, "fees international payments")
    assert found["found"] is True
    assert found["results"][0]["chunk_id"] == "how-does-relaypay-charge-fees"
    assert set(found["results"][0]) == {"chunk_id", "title", "text", "score"}

    missing = run(kb, "weather forecast pizza")
    assert (missing["found"], missing["results"]) == (False, [])
    assert "decline or escalate" in missing["note"].lower()


def test_bad_queries_are_rejected_without_crashing(kb):
    for query in ("   ", "fees " * MAX_QUERY_LENGTH):
        assert run(kb, query)["error"] == "invalid_query"


def test_searches_are_logged_but_bad_queries_are_not(kb):
    store = FakeLogStore()
    run(kb, "fees international payments", store)
    run(kb, "weather forecast pizza", store)
    run(kb, "", store)
    first, no_match = store.records  # exactly two
    assert (first.conversation_id, first.query) == ("call-1", "fees international payments")
    assert len(first.chunk_ids) == len(first.titles) == len(first.scores) > 0
    assert no_match.chunk_ids == ()


def test_log_failure_still_returns_results(kb):
    assert run(kb, "fees international payments", FakeLogStore(fail=True))["found"] is True


def test_search_crash_returns_structured_error():
    class BrokenKB:
        def search(self, query):
            raise RuntimeError("boom")

    result = search_knowledge_base("fees", kb=BrokenKB(), log_store=FakeLogStore(), conversation_id="c")
    assert (result["found"], result["error"]) == (False, "internal_error")
