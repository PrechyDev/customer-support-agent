"""Where retrieval records go (SPECS §7, PRD "Retrieval records").

Now: a JSON-lines file. Phase 2: a Supabase store with the same `record` method,
so the tool code doesn't change.
"""

import json
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class RetrievalRecord:
    conversation_id: str
    query: str
    chunk_ids: tuple[str, ...]
    titles: tuple[str, ...]
    scores: tuple[float, ...]
    duration_ms: float
    summaries: tuple[str, ...] = ()  # each chunk's first sentence (PRD "source summary")


class RetrievalLogStore(Protocol):
    def record(self, record: RetrievalRecord) -> None: ...


class JsonlRetrievalLogStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()  # several calls can search at once

    def record(self, record: RetrievalRecord) -> None:
        line = json.dumps({"timestamp": datetime.now(UTC).isoformat(), **asdict(record)})
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")


class SupabaseRetrievalLogStore:
    """Writes to retrieval_logs. Called in a worker thread; failures are caught by the knowledge tool."""

    def __init__(self, repo) -> None:
        self._repo = repo

    def record(self, record: RetrievalRecord) -> None:
        self._repo.log_retrieval(record.conversation_id, record.query, list(record.chunk_ids), list(record.titles),
                                 list(record.scores), list(record.summaries), record.duration_ms)


class BackgroundLogStore:
    """Hands each record to a worker thread so the search result isn't delayed by the write."""

    def __init__(self, inner: RetrievalLogStore) -> None:
        from concurrent.futures import ThreadPoolExecutor

        self._inner = inner
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="retrieval-log")

    def record(self, record: RetrievalRecord) -> None:
        self._executor.submit(self._write, record)

    def _write(self, record: RetrievalRecord) -> None:
        try:
            self._inner.record(record)
        except Exception:
            import logging
            logging.getLogger(__name__).warning("Could not write retrieval log (conversation=%s)", record.conversation_id)
