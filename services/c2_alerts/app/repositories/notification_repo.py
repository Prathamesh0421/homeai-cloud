"""Notifications (in-app record + one row per emailed contact)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.orm import Alert, Notification


class NotificationRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, notification: Notification) -> Notification:
        self.session.add(notification)
        self.session.flush()
        return notification

    def list_for_alert(self, alert_id: str) -> list[Notification]:
        """In-app first, then emails in contact priority order."""
        stmt = (
            select(Notification)
            .where(Notification.alert_id == alert_id)
            .order_by(
                Notification.channel != "in_app",
                Notification.priority.asc().nulls_first(),
                Notification.created_at,
                Notification.notification_id,
            )
        )
        return list(self.session.scalars(stmt))

    def due_for_retry(
        self, now: datetime, *, stuck_before: datetime, max_attempts: int, limit: int
    ) -> list[tuple[Notification, Alert]]:
        """Email rows to try again, oldest first, with their alert.

        ``failed`` rows whose next attempt is due (``next_attempt_at`` is NULL once given up),
        and ``queued`` rows created before ``stuck_before``: the process stopped between
        inserting the row and sending it.
        """
        due = and_(
            Notification.status == "failed",
            Notification.next_attempt_at <= now,
            Notification.attempt_count < max_attempts,
        )
        stuck = and_(Notification.status == "queued", Notification.created_at < stuck_before)
        stmt = (
            select(Notification, Alert)
            .join(Alert, Alert.alert_id == Notification.alert_id)
            .where(Notification.channel == "email", or_(due, stuck))
            .order_by(Notification.created_at, Notification.notification_id)
            .limit(limit)
        )
        return [(n, a) for n, a in self.session.execute(stmt).unique().all()]
