from pathlib import Path

import pytest

from customer_support_agent.kb.chunker import chunk_markdown
from customer_support_agent.kb.errors import KnowledgeBaseError

KB_PATH = Path(__file__).parents[2] / "data" / "relaypay-knowledge-base.md"


@pytest.fixture(scope="module")
def kb_chunks():
    return chunk_markdown(KB_PATH.read_text(encoding="utf-8"))


def test_real_kb_splits_into_37_chunks(kb_chunks):
    assert len(kb_chunks) == 37


def test_h1_intro_is_excluded(kb_chunks):
    assert all("approved support knowledge" not in c.text for c in kb_chunks)


def test_h2_intros_with_text_become_chunks(kb_chunks):
    headings = {c.heading for c in kb_chunks}
    assert "Product Features Overview" in headings
    assert "Policies And Compliance" in headings


def test_h2_without_text_is_not_a_chunk(kb_chunks):
    headings = {c.heading for c in kb_chunks}
    assert "Frequently Asked Questions" not in headings


def test_h3_chunk_keeps_its_section_and_text(kb_chunks):
    fees = next(c for c in kb_chunks if c.heading == "How Does RelayPay Charge Fees?")
    assert fees.section == "Frequently Asked Questions"
    assert fees.title == "Frequently Asked Questions > How Does RelayPay Charge Fees?"
    assert "displays applicable fees before a transaction is confirmed" in fees.text


def test_chunk_ids_are_unique_slugs(kb_chunks):
    ids = [c.id for c in kb_chunks]
    assert len(ids) == len(set(ids))
    fees = next(c for c in kb_chunks if c.heading == "How Does RelayPay Charge Fees?")
    assert fees.id == "how-does-relaypay-charge-fees"


def test_bullet_lists_stay_inside_their_chunk(kb_chunks):
    features = next(c for c in kb_chunks if c.heading == "Feature Availability And Limitations")
    assert "Cryptocurrency payments" in features.text


def test_empty_text_raises():
    with pytest.raises(KnowledgeBaseError, match="no chunks"):
        chunk_markdown("")


def test_headings_without_body_raise():
    with pytest.raises(KnowledgeBaseError, match="no chunks"):
        chunk_markdown("# Title\n\n## Empty section\n\n### Also empty\n")


def test_duplicate_headings_raise():
    text = "## Section\n\n### Fees\n\nOne.\n\n### Fees\n\nTwo.\n"
    with pytest.raises(KnowledgeBaseError, match="duplicate chunk id"):
        chunk_markdown(text)
