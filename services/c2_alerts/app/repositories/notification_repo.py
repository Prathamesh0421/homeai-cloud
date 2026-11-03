"""Notifications (in-app record + one row per emailed contact)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import Notification


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
