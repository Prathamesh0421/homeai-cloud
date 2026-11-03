"""Quiet hours in the house's timezone (C2 plan §4.1): wrap-around, boundaries, DST."""

from __future__ import annotations

from datetime import UTC, datetime, time

import pytest
from app.services.quiet_hours import in_quiet_hours

LA = "America/Los_Angeles"
NIGHT = (time(22, 0), time(7, 0))  # wraps midnight
AFTERNOON = (time(13, 0), time(15, 0))


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "window", "expected"),
    [
        # 2026-10-24 is PDT (UTC-7)
        (utc(2026, 10, 25, 6, 10), NIGHT, True),  # 23:10 local
        (utc(2026, 10, 25, 5, 0), NIGHT, True),  # 22:00 local: start is inclusive
        (utc(2026, 10, 25, 4, 59), NIGHT, False),  # 21:59 local
        (utc(2026, 10, 25, 13, 59), NIGHT, True),  # 06:59 local
        (utc(2026, 10, 25, 14, 0), NIGHT, False),  # 07:00 local: end is exclusive
        (utc(2026, 10, 25, 7, 30), NIGHT, True),  # 00:30 local (after midnight)
        (utc(2026, 10, 25, 21, 0), AFTERNOON, True),  # 14:00 local
        (utc(2026, 10, 25, 22, 0), AFTERNOON, False),  # 15:00 local
        (utc(2026, 10, 25, 19, 59), AFTERNOON, False),  # 12:59 local
    ],
)
def test_window_in_house_time(now, window, expected):
    assert in_quiet_hours(now, LA, *window) is expected


def test_uses_house_timezone_not_utc():
    now = utc(2026, 10, 25, 23, 30)  # 23:30 UTC = 16:30 in LA
    assert in_quiet_hours(now, "UTC", *NIGHT) is True
    assert in_quiet_hours(now, LA, *NIGHT) is False


def test_dst_fall_back_day():
    # 2026-11-01: LA moves from PDT (UTC-7) to PST (UTC-8) at 09:00 UTC.
    # 14:30 UTC is 06:30 PST (quiet). A fixed PDT offset would say 07:30 (not quiet).
    assert in_quiet_hours(utc(2026, 11, 1, 14, 30), LA, *NIGHT) is True
    assert in_quiet_hours(utc(2026, 11, 1, 15, 30), LA, *NIGHT) is False  # 07:30 PST
    assert in_quiet_hours(utc(2026, 11, 1, 8, 30), LA, *NIGHT) is True  # 01:30 PDT
    assert in_quiet_hours(utc(2026, 11, 1, 9, 30), LA, *NIGHT) is True  # 01:30 PST (again)


def test_dst_spring_forward_day():
    # 2026-03-08: PST -> PDT at 10:00 UTC. 13:30 UTC is 06:30 PDT (quiet); fixed PST: 05:30.
    assert in_quiet_hours(utc(2026, 3, 8, 13, 30), LA, *NIGHT) is True
    assert in_quiet_hours(utc(2026, 3, 8, 14, 30), LA, *NIGHT) is False  # 07:30 PDT


@pytest.mark.parametrize("window", [(None, None), (time(22, 0), None), (None, time(7, 0))])
def test_no_window_is_never_quiet(window):
    assert in_quiet_hours(utc(2026, 10, 25, 6, 10), LA, *window) is False


def test_equal_start_and_end_is_an_empty_window():
    assert in_quiet_hours(utc(2026, 10, 25, 6, 10), LA, time(23, 0), time(23, 0)) is False


def test_unknown_timezone_falls_back_to_utc():
    assert in_quiet_hours(utc(2026, 10, 25, 23, 0), "Mars/Olympus_Mons", *NIGHT) is True
    assert in_quiet_hours(utc(2026, 10, 25, 12, 0), "Mars/Olympus_Mons", *NIGHT) is False


def test_naive_now_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        in_quiet_hours(datetime(2026, 10, 25, 6, 10), LA, *NIGHT)


def test_default_clock_is_utc_aware():
    from app.services.quiet_hours import utc_now

    assert utc_now().utcoffset().total_seconds() == 0
