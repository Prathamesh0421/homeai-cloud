"""Fixed-window rate limiter kept in Postgres, so every C2 copy counts against one limit (S-5).

Each hit upserts the row for (bucket, key, current window) and reads the new count back in one
statement. Windows are aligned on the database clock, so copies on different hosts agree.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

_HIT = text(
    """
    WITH w AS (
        SELECT to_timestamp(floor(extract(epoch FROM now()) / :window) * :window) AS start
    )
    INSERT INTO c2.rate_limit_hits AS r (bucket, key, window_start, hits)
    SELECT :bucket, :key, w.start, 1 FROM w
    ON CONFLICT (bucket, key, window_start) DO UPDATE SET hits = r.hits + 1
    RETURNING r.hits,
              ceil(extract(epoch FROM r.window_start + make_interval(secs => :window) - now()))
    """
)
_SWEEP = text(
    "DELETE FROM c2.rate_limit_hits"
    " WHERE bucket = :bucket AND window_start < now() - make_interval(secs => :window)"
)


class PostgresRateLimiter:
    """At most ``limit`` hits per ``window_s``-second window per key (e.g. client IP)."""

    def __init__(
        self,
        bucket: str,
        limit: int,
        window_s: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.bucket = bucket
        self.limit = limit
        self.window_s = window_s
        self.clock = clock
        self._last_sweep = clock()

    def hit(self, session: Session, key: str) -> int:
        """Record a hit and commit it (it counts even if the request then fails).

        Returns 0 if allowed, else seconds until the next window opens.
        """
        params = {"bucket": self.bucket, "window": self.window_s}
        hits, retry_after = session.execute(_HIT, {**params, "key": key[:64]}).one()
        if self.clock() - self._last_sweep >= self.window_s:  # past windows, once per window
            self._last_sweep = self.clock()
            session.execute(_SWEEP, params)
        session.commit()
        return 0 if hits <= self.limit else max(1, int(retry_after))
