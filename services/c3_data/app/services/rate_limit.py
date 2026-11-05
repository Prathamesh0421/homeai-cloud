"""In-process sliding-window rate limiter (one C3 API process per host, per the plan).

Used for the Records API limit (> 60 requests/min/user -> 429). Keyed by user id.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    """At most ``limit`` hits per ``window_s`` seconds per key (e.g. user id)."""

    def __init__(
        self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window_s = window_s
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_sweep = clock()

    def hit(self, key: str) -> int:
        """Record a hit. Returns 0 if allowed, else seconds until the next hit is allowed."""
        now = self.clock()
        with self._lock:
            self._sweep(now)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1, math.ceil(hits[0] + self.window_s - now))
            hits.append(now)
            return 0

    def _sweep(self, now: float) -> None:
        # Forget idle keys once per window so memory stays bounded.
        if now - self._last_sweep < self.window_s:
            return
        self._last_sweep = now
        cutoff = now - self.window_s
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
            del self._hits[key]
