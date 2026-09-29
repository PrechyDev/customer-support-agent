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
