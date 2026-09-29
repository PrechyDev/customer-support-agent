from datetime import UTC, datetime
from pathlib import Path

import pytest

from customer_support_agent.agent.prompt import BEHAVIOUR_CHUNK_IDS, build_system_prompt
from customer_support_agent.kb import KBChunk, KnowledgeBase, KnowledgeBaseError

KB_PATH = Path(__file__).parents[2] / "data" / "relaypay-knowledge-base.md"
NOW = datetime(2026, 9, 29, 14, 5, tzinfo=UTC)


def test_prompt_is_assembled_from_the_kb_and_current_time():
    kb = KnowledgeBase.from_file(KB_PATH)
    prompt = build_system_prompt(kb, NOW)
    assert all(chunk.title in prompt for chunk in kb.chunks)  # search vocabulary
    assert all(kb.get(i).text in prompt for i in BEHAVIOUR_CHUNK_IDS)  # policy comes from the KB, not a copy
    assert "Tuesday 29 September 2026, 14:05 UTC" in prompt


def test_missing_policy_section_fails_fast():
    kb = KnowledgeBase([KBChunk(id="fees", section="FAQ", heading="Fees", text="Fees vary.")])
    with pytest.raises(KnowledgeBaseError, match="no chunk with id"):
        build_system_prompt(kb, NOW)
