"""In-memory BM25 search over the knowledge base (SPECS §7).

The KB is loaded once at startup. Each chunk is indexed on its own heading plus
its text, but not its parent section name: adding "Policies And Compliance" to
every policy chunk would make "compliance" match all of them.
"""

import logging
import re
from pathlib import Path

import snowballstemmer
from rank_bm25 import BM25Okapi

from customer_support_agent.kb.chunker import chunk_markdown
from customer_support_agent.kb.errors import KnowledgeBaseError
from customer_support_agent.kb.models import KBChunk, SearchResult

logger = logging.getLogger(__name__)

# 5, not 3: multi-section questions (e.g. scenario 8) need 2-3 chunks, and a
# missed chunk costs more than ~200 tokens of noise.
DEFAULT_TOP_K = 5

# Common words that would otherwise match FAQ headings ("What Is RelayPay?")
# without saying anything about the topic.
_STOPWORDS = frozenset(
    "a an and are as at be but by can do does for from how i if in is it its "
    "me my of on or our so that the their this to was we what when where which "
    "who why will with you your".split()
)
_WORD = re.compile(r"[a-z0-9]+")
_stemmer = snowballstemmer.stemmer("english")


def tokenize(text: str) -> list[str]:
    words = [w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS]
    return _stemmer.stemWords(words)


class KnowledgeBase:
    def __init__(self, chunks: list[KBChunk]) -> None:
        if not chunks:
            raise KnowledgeBaseError("Knowledge base has no chunks to index")
        self._chunks = tuple(chunks)
        self._index = BM25Okapi([tokenize(f"{c.heading}\n{c.text}") for c in self._chunks])

    @classmethod
    def from_file(cls, path: Path) -> "KnowledgeBase":
        try:
            text = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise KnowledgeBaseError(f"Knowledge base file not found: {path}") from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise KnowledgeBaseError(f"Knowledge base file could not be read: {path} ({exc})") from exc

        kb = cls(chunk_markdown(text))
        logger.info("Loaded knowledge base: %d chunks from %s", kb.chunk_count, path)
        return kb

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[SearchResult]:
        """Best-matching chunks, highest score first. Empty list means nothing relevant."""
        if top_k < 1:
            raise ValueError(f"top_k must be at least 1, got {top_k}")

        terms = tokenize(query or "")
        if not terms:
            logger.warning("Knowledge base search skipped: query has no searchable words")
            return []

        scores = self._index.get_scores(terms)
        ranked = sorted(zip(self._chunks, scores), key=lambda pair: pair[1], reverse=True)
        results = [SearchResult(chunk=c, score=float(s)) for c, s in ranked[:top_k] if s > 0]

        logger.debug(
            "Knowledge base search: terms=%s results=%s",
            terms,
            [(r.chunk.id, round(r.score, 2)) for r in results],
        )
        return results
