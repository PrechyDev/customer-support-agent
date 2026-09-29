"""Split the knowledge base markdown into heading-based chunks (SPECS §7).

Rules:
- Each H3 section is a chunk.
- An H2 section is a chunk only if it has its own intro text.
- The H1 intro describes the file itself, so it is never a chunk.
- Deeper headings (H4+) are treated as body text.
"""

import logging
import re
from dataclasses import dataclass, field

from customer_support_agent.kb.errors import KnowledgeBaseError
from customer_support_agent.kb.models import KBChunk

logger = logging.getLogger(__name__)

_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_CHUNK_LEVELS = (2, 3)


@dataclass
class _Section:
    """A heading and the lines under it, before we decide if it's a chunk."""

    level: int
    section: str  # parent H2 heading
    heading: str
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


def slugify(heading: str) -> str:
    """'How Does RelayPay Charge Fees?' -> 'how-does-relaypay-charge-fees'."""
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def _split_sections(text: str) -> list[_Section]:
    """Group the file into sections: every heading starts a new one.

    A section is added to the list as soon as its heading is seen, and body
    lines are added to whichever section is current. So the last section in
    the file needs no special handling.
    """
    sections: list[_Section] = []
    parent = ""
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            level, heading = len(match.group(1)), match.group(2)
            if level == 2:
                parent = heading
            sections.append(_Section(level=level, section=parent, heading=heading))
        elif sections:
            sections[-1].lines.append(line)
        # Lines before the first heading belong to no section and are ignored.
    return sections


def _check_unique_ids(chunks: list[KBChunk]) -> None:
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.id in seen:
            raise KnowledgeBaseError(f"Knowledge base has a duplicate chunk id: '{chunk.id}'")
        seen.add(chunk.id)


def chunk_markdown(text: str) -> list[KBChunk]:
    chunks = [
        KBChunk(id=slugify(s.heading), section=s.section, heading=s.heading, text=s.text)
        for s in _split_sections(text)
        if s.level in _CHUNK_LEVELS and s.text
    ]
    if not chunks:
        raise KnowledgeBaseError("Knowledge base produced no chunks: check the file has H2/H3 sections with text")
    _check_unique_ids(chunks)

    logger.debug("Chunked knowledge base into %d chunks", len(chunks))
    return chunks
