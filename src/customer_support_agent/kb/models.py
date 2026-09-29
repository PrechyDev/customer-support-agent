from dataclasses import dataclass


@dataclass(frozen=True)
class KBChunk:
    """One searchable section of the knowledge base."""

    id: str  # stable slug of the heading, used in retrieval logs
    section: str  # parent H2 heading
    heading: str  # the chunk's own heading (H3, or the H2 for section intros)
    text: str  # body text under the heading

    @property
    def title(self) -> str:
        """Source title for logs and citations, e.g. 'FAQ > How Does RelayPay Charge Fees?'."""
        if self.section == self.heading:
            return self.heading
        return f"{self.section} > {self.heading}"


@dataclass(frozen=True)
class SearchResult:
    chunk: KBChunk
    score: float
