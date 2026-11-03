"""Sliding-window rate limiter for the public alert view (60 requests/min/IP)."""

from __future__ import annotations

import threading

from app.services.rate_limit import SlidingWindowLimiter


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_allows_the_limit_then_blocks_with_retry_after():
    clock = Clock()
    limiter = SlidingWindowLimiter(limit=60, window_s=60, clock=clock)
    assert all(limiter.hit("1.2.3.4") == 0 for _ in range(60))
    assert limiter.hit("1.2.3.4") == 60
    clock.t += 15
    assert limiter.hit("1.2.3.4") == 45  # oldest hit leaves the window in 45 s


def test_window_slides():
    clock = Clock()
    limiter = SlidingWindowLimiter(limit=2, window_s=60, clock=clock)
    assert limiter.hit("a") == 0
    clock.t += 30
    assert limiter.hit("a") == 0
    assert limiter.hit("a") > 0
    clock.t += 31  # first hit expired
    assert limiter.hit("a") == 0


def test_blocked_hits_do_not_extend_the_block():
    clock = Clock()
    limiter = SlidingWindowLimiter(limit=1, window_s=60, clock=clock)
    limiter.hit("a")
    for _ in range(10):
        limiter.hit("a")
    clock.t += 60.5
    assert limiter.hit("a") == 0


def test_keys_are_independent():
    limiter = SlidingWindowLimiter(limit=1, window_s=60, clock=Clock())
    assert limiter.hit("a") == 0
    assert limiter.hit("a") > 0
    assert limiter.hit("b") == 0


def test_idle_keys_are_forgotten():
    clock = Clock()
    limiter = SlidingWindowLimiter(limit=5, window_s=60, clock=clock)
    for ip in ("a", "b", "c"):
        limiter.hit(ip)
    clock.t += 120
    limiter.hit("d")
    assert set(limiter._hits) == {"d"}


def test_thread_safe():
    limiter = SlidingWindowLimiter(limit=100, window_s=60)
    allowed = []

    def burst():
        allowed.extend(1 for _ in range(50) if limiter.hit("x") == 0)

    threads = [threading.Thread(target=burst) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(allowed) == 100
