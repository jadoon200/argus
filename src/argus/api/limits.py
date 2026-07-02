"""Public-deployment guards for the expensive /brief route.

In-memory, single-process: a per-client sliding-window rate limit and a bounded
concurrency cap so a traffic spike degrades to 429/503 instead of running the box
(or the LLM bill) into the ground. The reverse proxy is the primary defence; these are
belt-and-suspenders. See docs/DEPLOY.md.
"""

import time
from collections import defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from threading import BoundedSemaphore, Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: float, trust_forwarded: bool) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._trust_forwarded = trust_forwarded
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()
        self._last_sweep = time.monotonic()

    def _client_key(self, request: "Request") -> str:
        if self._trust_forwarded:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _sweep(self, now: float) -> None:
        """Drop clients whose every hit has aged out — without this, one-off clients
        (e.g. a scan from many IPs) would accumulate keys forever."""
        if now - self._last_sweep < self._window:
            return
        self._last_sweep = now
        cutoff = now - self._window
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]

    def allow(self, request: "Request") -> bool:
        now = time.monotonic()
        key = self._client_key(request)
        with self._lock:
            self._sweep(now)
            hits = self._hits[key]
            while hits and hits[0] <= now - self._window:
                hits.popleft()
            if len(hits) >= self._max:
                return False
            hits.append(now)
            return True


class SlotUnavailable(Exception):
    """Raised when a concurrency slot can't be acquired within the timeout."""


class ConcurrencyLimiter:
    def __init__(self, limit: int, acquire_timeout: float) -> None:
        self._sem = BoundedSemaphore(limit)
        self._timeout = acquire_timeout

    @contextmanager
    def slot(self) -> Iterator[None]:
        if not self._sem.acquire(timeout=self._timeout):
            raise SlotUnavailable
        try:
            yield
        finally:
            self._sem.release()
