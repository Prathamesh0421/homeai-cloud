"""Quiet hours: a house-local window (may wrap midnight) that holds medium/low alerts."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)


@lru_cache(maxsize=256)
def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        # C1 validates timezones; if a bad one slips through, fail safe on UTC and say so.
        logger.warning("unknown house timezone, using UTC", extra={"timezone": name})
        return ZoneInfo("UTC")


def in_quiet_hours(
    now: datetime, timezone: str, quiet_start: time | None, quiet_end: time | None
) -> bool:
    """True if ``now`` falls in ``[quiet_start, quiet_end)`` on the house's local clock.

    ``22:00-07:00`` wraps midnight. Missing either bound, or start == end, means no window.
    DST is handled by converting ``now`` with the house's IANA zone.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if quiet_start is None or quiet_end is None or quiet_start == quiet_end:
        return False
    local = now.astimezone(_zone(timezone or "UTC")).time().replace(tzinfo=None)
    if quiet_start < quiet_end:
        return quiet_start <= local < quiet_end
    return local >= quiet_start or local < quiet_end


def utc_now() -> datetime:
    return datetime.now(UTC)
