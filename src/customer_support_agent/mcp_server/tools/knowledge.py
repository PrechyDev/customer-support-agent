"""The search_knowledge_base tool logic, kept free of MCP so it can be tested directly."""

import logging
import time
from typing import Any, Protocol

from customer_support_agent.kb import SearchResult
from customer_support_agent.mcp_server.retrieval_log import RetrievalLogStore, RetrievalRecord

logger = logging.getLogger(__name__)

MAX_QUERY_LENGTH = 300

DESCRIPTION = (
    "Search RelayPay's approved support knowledge base. Use it for product and policy questions "
    "(fees, payment timelines, invoicing, verification, restrictions, disputes, limitations). "
    "Do not use it for greetings or for account, transaction or payout lookups. "
    "Before searching, rewrite the customer's words into the knowledge base's own terms "
    "(e.g. 'my payment is stuck' -> 'payment delayed'). "
    "Answer only from the returned text. If found is false, do not answer from general knowledge: "
    "decline or escalate."
)

_NO_MATCH_NOTE = "No approved knowledge found. Decline or escalate; do not answer from general knowledge."


class Searchable(Protocol):
    def search(self, query: str) -> list[SearchResult]: ...


def _invalid(reason: str) -> dict[str, Any]:
    return {"found": False, "results": [], "error": "invalid_query", "note": reason}


def search_knowledge_base(
    query: str, *, kb: Searchable, log_store: RetrievalLogStore, conversation_id: str
) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return _invalid("The query is empty. Search with the topic of the customer's question.")
    if len(query) > MAX_QUERY_LENGTH:
        return _invalid(f"The query is longer than {MAX_QUERY_LENGTH} characters. Search with a few key words.")

    started = time.perf_counter()
    try:
        results = kb.search(query)
    except Exception:
        logger.exception("Knowledge base search failed (conversation=%s)", conversation_id)
        return {"found": False, "results": [], "error": "internal_error",
                "note": "Knowledge search failed. Apologise and offer to escalate."}
    duration_ms = (time.perf_counter() - started) * 1000

    _log_retrieval(log_store, conversation_id, query, results, duration_ms)

    if not results:
        return {"found": False, "results": [], "note": _NO_MATCH_NOTE}
    return {
        "found": True,
        "results": [
            {"chunk_id": r.chunk.id, "title": r.chunk.title, "text": r.chunk.text, "score": round(r.score, 2)}
            for r in results
        ],
    }


def _log_retrieval(
    log_store: RetrievalLogStore, conversation_id: str, query: str, results: list[SearchResult], duration_ms: float
) -> None:
    """Logging must never break the reply: failures are reported, then ignored."""
    record = RetrievalRecord(
        conversation_id=conversation_id,
        query=query,
        chunk_ids=tuple(r.chunk.id for r in results),
        titles=tuple(r.chunk.title for r in results),
        scores=tuple(round(r.score, 2) for r in results),
        duration_ms=round(duration_ms, 3),
    )
    try:
        log_store.record(record)
    except Exception:
        logger.exception("Could not write retrieval log (conversation=%s)", conversation_id)
