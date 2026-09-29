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


def run(kb, query, store=None, conversation_id="call-1"):
    return search_knowledge_base(query, kb=kb, log_store=store or FakeLogStore(), conversation_id=conversation_id)


def test_returns_matching_chunks(kb):
    result = run(kb, "fees international payments")
    assert result["found"] is True
    top = result["results"][0]
    assert top["chunk_id"] == "how-does-relaypay-charge-fees"
    assert top["title"] == "Frequently Asked Questions > How Does RelayPay Charge Fees?"
    assert "fees" in top["text"].lower()
    assert isinstance(top["score"], float)


def test_no_match_tells_agent_to_decline(kb):
    result = run(kb, "weather forecast pizza")
    assert result["found"] is False
    assert result["results"] == []
    assert "decline or escalate" in result["note"].lower()


@pytest.mark.parametrize("query", ["", "   "])
def test_empty_query_is_rejected(kb, query):
    result = run(kb, query)
    assert result["found"] is False
    assert result["error"] == "invalid_query"


def test_too_long_query_is_rejected(kb):
    result = run(kb, "fees " * MAX_QUERY_LENGTH)
    assert result["error"] == "invalid_query"


def test_every_search_is_logged(kb):
    store = FakeLogStore()
    run(kb, "fees international payments", store=store, conversation_id="call-42")
    run(kb, "weather forecast pizza", store=store, conversation_id="call-42")

    assert len(store.records) == 2
    first, no_match = store.records
    assert first.conversation_id == "call-42"
    assert first.query == "fees international payments"
    assert first.chunk_ids[0] == "how-does-relaypay-charge-fees"
    assert len(first.chunk_ids) == len(first.titles) == len(first.scores)
    assert first.duration_ms >= 0
    assert no_match.chunk_ids == ()


def test_invalid_query_is_not_logged_as_a_retrieval(kb):
    store = FakeLogStore()
    run(kb, "", store=store)
    assert store.records == []


def test_log_failure_still_returns_results(kb):
    result = run(kb, "fees international payments", store=FakeLogStore(fail=True))
    assert result["found"] is True


def test_unexpected_search_error_returns_structured_error(kb):
    class BrokenKB:
        def search(self, query):
            raise RuntimeError("boom")

    result = search_knowledge_base("fees", kb=BrokenKB(), log_store=FakeLogStore(), conversation_id="c")
    assert result == {"found": False, "results": [], "error": "internal_error",
                      "note": "Knowledge search failed. Apologise and offer to escalate."}
