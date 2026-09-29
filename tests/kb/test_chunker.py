from pathlib import Path

import pytest

from customer_support_agent.kb.chunker import chunk_markdown
from customer_support_agent.kb.errors import KnowledgeBaseError

KB_PATH = Path(__file__).parents[2] / "data" / "relaypay-knowledge-base.md"


def test_real_kb_splits_by_heading_rules():
    chunks = chunk_markdown(KB_PATH.read_text(encoding="utf-8"))
    headings = {c.heading for c in chunks}
    assert len(chunks) == 37
    assert "RelayPay Knowledge Base" not in headings  # H1 intro excluded
    assert {"Product Features Overview", "Policies And Compliance"} <= headings  # H2 intros with text
    assert "Frequently Asked Questions" not in headings  # H2 with no text
    assert len({c.id for c in chunks}) == 37  # ids unique


def test_chunk_keeps_section_title_text_and_slug_id():
    fees = next(c for c in chunk_markdown(KB_PATH.read_text(encoding="utf-8"))
                if c.heading == "How Does RelayPay Charge Fees?")
    assert fees.id == "how-does-relaypay-charge-fees"
    assert fees.title == "Frequently Asked Questions > How Does RelayPay Charge Fees?"
    assert "displays applicable fees before a transaction is confirmed" in fees.text


def test_no_usable_chunks_raises():
    for text in ("", "# Title\n\n## Empty\n\n### Also empty\n"):
        with pytest.raises(KnowledgeBaseError, match="no chunks"):
            chunk_markdown(text)


def test_duplicate_headings_raise():
    with pytest.raises(KnowledgeBaseError, match="duplicate chunk id"):
        chunk_markdown("## S\n\n### Fees\n\nOne.\n\n### Fees\n\nTwo.\n")
