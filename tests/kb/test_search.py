from pathlib import Path

import pytest

from customer_support_agent.kb.errors import KnowledgeBaseError
from customer_support_agent.kb.search import KnowledgeBase

KB_PATH = Path(__file__).parents[2] / "data" / "relaypay-knowledge-base.md"


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase.from_file(KB_PATH)


def ids(results):
    return [r.chunk.id for r in results]


def test_scenario_queries_find_the_right_chunks(kb):
    # Written the way the agent rewrites them into KB terms. The raw caller wording for
    # scenario 8 ("guarantee payout arrival time") misses: "time" matches the verification FAQ.
    assert ids(kb.search("fees international payments"))[0] == "how-does-relaypay-charge-fees"
    guarantee = ids(kb.search("guarantee payout timelines how long payments take", top_k=3))
    assert {"can-relaypay-guarantee-payment-timelines", "how-long-do-payments-take-to-process"} <= set(guarantee)
    assert "why-is-my-payment-delayed" in ids(kb.search("payment delayed", top_k=3))
    assert "account-restrictions-and-suspensions" in ids(kb.search("account restricted", top_k=3))


def test_asking_an_faq_question_finds_that_faq(kb):
    # "what is relaypay" is just "relaypay" after common words are dropped, and that word is in
    # nearly every chunk. The whole-heading match puts the FAQ first (a problem found in a real call).
    assert ids(kb.search("what is relaypay"))[0] == "what-is-relaypay"
    assert ids(kb.search("why is my payment delayed"))[0] == "why-is-my-payment-delayed"


def test_stemming_matches_word_roots(kb):
    assert "why-is-my-payment-delayed" in ids(kb.search("delaying delays", top_k=3))  # KB says "delayed"


def test_results_are_ranked_positive_and_limited(kb):
    results = kb.search("payment payout invoice fees account")
    assert len(results) == 5  # default top_k
    assert [r.score for r in results] == sorted((r.score for r in results), reverse=True)
    assert all(r.score > 0 for r in results)
    assert len(kb.search("payout beneficiary", top_k=2)) == 2


def test_irrelevant_queries_return_nothing(kb):
    for query in ("", "   ", "what is the", "weather forecast pizza"):
        assert kb.search(query) == []


def test_invalid_top_k_raises(kb):
    with pytest.raises(ValueError):
        kb.search("fees", top_k=0)


def test_load_errors_are_clear(tmp_path):
    with pytest.raises(KnowledgeBaseError, match="not found"):
        KnowledgeBase.from_file(tmp_path / "missing.md")
    empty = tmp_path / "empty.md"
    empty.write_text("# Just a title\n", encoding="utf-8")
    with pytest.raises(KnowledgeBaseError, match="no chunks"):
        KnowledgeBase.from_file(empty)


def test_get_by_id(kb):
    assert kb.get("communications").heading == "Communications"
    with pytest.raises(KnowledgeBaseError, match="no chunk with id 'nope'"):
        kb.get("nope")
