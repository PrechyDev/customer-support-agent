from pathlib import Path

import pytest

from customer_support_agent.kb.errors import KnowledgeBaseError
from customer_support_agent.kb.search import KnowledgeBase

KB_PATH = Path(__file__).parents[2] / "data" / "relaypay-knowledge-base.md"


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase.from_file(KB_PATH)


def top_ids(results):
    return [r.chunk.id for r in results]


# --- Test-scenario queries, written the way the agent would rewrite them ---

def test_fees_question_finds_fees_faq_first(kb):
    results = kb.search("fees international payments")
    assert top_ids(results)[0] == "how-does-relaypay-charge-fees"


def test_guarantee_question_finds_guarantee_and_timelines(kb):
    # Scenario 8, as the agent rewrites it into KB terms. The raw caller wording
    # ("guarantee payout arrival time") misses: "time" matches the verification FAQ.
    ids = top_ids(kb.search("guarantee payout timelines how long payments take", top_k=3))
    assert "can-relaypay-guarantee-payment-timelines" in ids
    assert "how-long-do-payments-take-to-process" in ids


def test_delayed_payment_finds_why_delayed(kb):
    ids = top_ids(kb.search("payment delayed", top_k=3))
    assert "why-is-my-payment-delayed" in ids


def test_restriction_finds_restriction_policy(kb):
    ids = top_ids(kb.search("account restricted", top_k=3))
    assert "account-restrictions-and-suspensions" in ids


# --- Stemming ---

def test_stemming_matches_word_roots(kb):
    # "delays" / "delaying" never appear in the KB; "delayed" / "delay" do.
    ids = top_ids(kb.search("delaying delays", top_k=3))
    assert "why-is-my-payment-delayed" in ids


# --- Results shape ---

def test_results_are_sorted_by_score_and_limited(kb):
    results = kb.search("payout beneficiary", top_k=2)
    assert len(results) == 2
    assert results[0].score >= results[1].score


def test_default_returns_up_to_five(kb):
    assert len(kb.search("payment payout invoice fees account")) == 5


def test_every_result_has_positive_score(kb):
    assert all(r.score > 0 for r in kb.search("exchange rates fixed"))


# --- What can go wrong ---

def test_empty_query_returns_nothing(kb):
    assert kb.search("") == []
    assert kb.search("   ") == []


def test_query_with_no_kb_words_returns_nothing(kb):
    assert kb.search("weather forecast pizza") == []


def test_stopword_only_query_returns_nothing(kb):
    assert kb.search("what is the") == []


def test_invalid_top_k_raises(kb):
    with pytest.raises(ValueError):
        kb.search("fees", top_k=0)


def test_missing_file_raises_clear_error(tmp_path):
    with pytest.raises(KnowledgeBaseError, match="not found"):
        KnowledgeBase.from_file(tmp_path / "missing.md")


def test_file_with_no_chunks_raises(tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_text("# Just a title\n", encoding="utf-8")
    with pytest.raises(KnowledgeBaseError, match="no chunks"):
        KnowledgeBase.from_file(empty)


def test_chunk_count_is_exposed(kb):
    assert kb.chunk_count == 37
