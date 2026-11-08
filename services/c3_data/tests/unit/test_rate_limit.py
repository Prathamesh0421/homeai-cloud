"""C3-10 (unit): sliding-window limiter (60/min semantics, retry-after)."""

from __future__ import annotations

from app.services.rate_limit import SlidingWindowLimiter


def test_allows_up_to_limit_then_blocks():
    t = [0.0]
    lim = SlidingWindowLimiter(limit=3, window_s=60, clock=lambda: t[0])
    assert [lim.hit("u1") for _ in range(3)] == [0, 0, 0]
    retry = lim.hit("u1")
    assert retry > 0  # 4th hit blocked, returns seconds until allowed


def test_window_slides():
    t = [0.0]
    lim = SlidingWindowLimiter(limit=1, window_s=10, clock=lambda: t[0])
    assert lim.hit("u1") == 0
    assert lim.hit("u1") > 0
    t[0] = 11.0  # past the window
    assert lim.hit("u1") == 0


def test_keys_independent():
    t = [0.0]
    lim = SlidingWindowLimiter(limit=1, window_s=60, clock=lambda: t[0])
    assert lim.hit("u1") == 0
    assert lim.hit("u2") == 0  # different user, own budget
