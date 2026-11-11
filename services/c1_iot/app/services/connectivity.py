"""Connectivity rules (C1 plan §4.2) — applied to enabled, non-archived feeds.

| Condition | connectivity_status | status |
|---|---|---|
| ``last_clip_at`` is null | ``unknown`` | unchanged (``provisioned``) |
| ``now - last_clip_at <= capture_interval_s`` | ``online`` | ``active`` (unless ``error``) |
| otherwise | ``offline`` | ``inactive`` (unless ``error``) |

``derive`` is the rule for one feed (unit-tested row by row); ``ConnectivityMonitor`` applies the
same rule in three set-based UPDATEs, touching only rows whose values change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, case, func, or_, update
from sqlalchemy.orm import Session

from app.models import CameraFeed


def derive(
    *, last_clip_at: datetime | None, capture_interval_s: int, status: str, now: datetime
) -> tuple[str, str]:
    """``(connectivity_status, status)`` for one enabled feed."""
    if last_clip_at is None:
        return "unknown", status
    if now - last_clip_at <= timedelta(seconds=capture_interval_s):
        return "online", status if status == "error" else "active"
    return "offline", status if status == "error" else "inactive"


@dataclass(frozen=True)
class MonitorResult:
    unknown: int
    online: int
    offline: int


class ConnectivityMonitor:
    def __init__(self, session: Session):
        self.session = session

    def run(self, now: datetime) -> MonitorResult:
        feed = CameraFeed
        live = and_(feed.is_enabled.is_(True), feed.archived_at.is_(None))
        interval = func.make_interval(
            0, 0, 0, 0, 0, 0, feed.config["capture_interval_s"].as_integer()
        )
        fresh = feed.last_clip_at + interval >= now
        keep_error = lambda target: case((feed.status == "error", "error"), else_=target)  # noqa: E731

        unknown = self.session.execute(
            update(feed)
            .where(live, feed.last_clip_at.is_(None), feed.connectivity_status != "unknown")
            .values(connectivity_status="unknown", updated_at=now)
            .execution_options(synchronize_session=False)
        ).rowcount
        online = self.session.execute(
            update(feed)
            .where(
                live,
                feed.last_clip_at.is_not(None),
                fresh,
                or_(feed.connectivity_status != "online", feed.status.not_in(("active", "error"))),
            )
            .values(connectivity_status="online", status=keep_error("active"), updated_at=now)
            .execution_options(synchronize_session=False)
        ).rowcount
        offline = self.session.execute(
            update(feed)
            .where(
                live,
                feed.last_clip_at.is_not(None),
                ~fresh,
                or_(
                    feed.connectivity_status != "offline",
                    feed.status.not_in(("inactive", "error")),
                ),
            )
            .values(connectivity_status="offline", status=keep_error("inactive"), updated_at=now)
            .execution_options(synchronize_session=False)
        ).rowcount
        return MonitorResult(unknown=unknown, online=online, offline=offline)
