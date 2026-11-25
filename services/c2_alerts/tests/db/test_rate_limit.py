"""S-5: the alert-view rate limit counts in Postgres, so it holds across C2 copies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.rate_limit import PostgresRateLimiter
from sqlalchemy import text


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _rows(session, bucket="t"):
    return session.execute(
        text("SELECT key, hits FROM c2.rate_limit_hits WHERE bucket = :b ORDER BY key"),
        {"b": bucket},
    ).all()


def test_allows_the_limit_then_blocks_until_the_next_window(session):
    limiter = PostgresRateLimiter("t", limit=3, window_s=60)
    assert [limiter.hit(session, "1.2.3.4") for _ in range(3)] == [0, 0, 0]
    retry_after = limiter.hit(session, "1.2.3.4")
    assert 1 <= retry_after <= 60
    assert _rows(session) == [("1.2.3.4", 4)]


def test_copies_share_one_count(session):
    # Two C2 copies = two limiter objects; only the database row is shared.
    a = PostgresRateLimiter("t", limit=2, window_s=60)
    b = PostgresRateLimiter("t", limit=2, window_s=60)
    assert a.hit(session, "ip") == 0
    assert b.hit(session, "ip") == 0
    assert a.hit(session, "ip") > 0
    assert b.hit(session, "ip") > 0


def test_keys_and_buckets_are_independent(session):
    limiter = PostgresRateLimiter("t", limit=1, window_s=60)
    other = PostgresRateLimiter("other", limit=1, window_s=60)
    assert limiter.hit(session, "a") == 0
    assert limiter.hit(session, "a") > 0
    assert limiter.hit(session, "b") == 0
    assert other.hit(session, "a") == 0


def test_a_new_window_starts_from_zero(session):
    # A full count in the previous window does not block the current one.
    session.execute(
        text(
            "INSERT INTO c2.rate_limit_hits VALUES ('t', 'a',"
            " to_timestamp(floor(extract(epoch FROM now()) / 60) * 60) - interval '60 seconds', 99)"
        )
    )
    assert PostgresRateLimiter("t", limit=1, window_s=60).hit(session, "a") == 0


def test_past_windows_are_swept_once_per_window(session):
    old = datetime.now(UTC) - timedelta(minutes=10)
    session.execute(
        text("INSERT INTO c2.rate_limit_hits VALUES ('t', 'old', :w, 5), ('other', 'old', :w, 5)"),
        {"w": old},
    )
    clock = Clock()
    limiter = PostgresRateLimiter("t", limit=5, window_s=60, clock=clock)
    limiter.hit(session, "new")
    assert [k for k, _ in _rows(session)] == ["new", "old"]  # not yet a window since start
    clock.t += 60
    limiter.hit(session, "new")
    assert _rows(session) == [("new", 2)]
    assert _rows(session, "other") == [("old", 5)]  # another bucket's rows are its own


def test_long_keys_are_truncated(session):
    PostgresRateLimiter("t", limit=1, window_s=60).hit(session, "x" * 100)
    assert _rows(session) == [("x" * 64, 1)]
