"""A small in-memory rate limiter (sliding window). One process serves everything (Cloud Run max-instances 1),
so memory is enough; a multi-instance deploy would move this to Redis or the database.
"""

import time
from collections import deque
from collections.abc import Callable

from fastapi import Request


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.window, self._clock = limit, window_seconds, clock
        self._hits: dict[str, deque[float]] = {}

    def _recent(self, key: str) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        cutoff = self._clock() - self.window
        while hits and hits[0] < cutoff:
            hits.popleft()
        return hits

    def blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.limit

    def hit(self, key: str) -> bool:
        """Counts one request; True if it's over the limit (and so should be refused)."""
        hits = self._recent(key)
        if len(hits) >= self.limit:
            return True
        hits.append(self._clock())
        if len(self._hits) > 10_000:  # bound memory: drop keys with no recent hits
            for stale in [k for k, v in self._hits.items() if not v]:
                del self._hits[stale]
        return False

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


def client_ip(request: Request) -> str:
    """The caller's address. On Cloud Run the first X-Forwarded-For entry is the client (set by Google's proxy)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
