"""Alert notifications (C2 plan §4.3): in-app record always; emails for critical/high.

Each email notification row moves ``queued -> sent | failed``. Failures keep ``attempt_count``,
``last_error`` and ``next_attempt_at`` so the NotificationRetry job (C2-10) can try again.
Rows are committed one by one so a crash never loses track of who was already emailed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.gateways.notifier import Notifier, NotifierError, describe
from app.gateways.types import Contact, DependencyUnavailableError, HouseReader, SettingsReader
from app.models.orm import Alert, Notification
from app.repositories.notification_repo import NotificationRepository
from app.services.email_render import EmailFacts, render_email
from app.services.quiet_hours import utc_now
from app.services.signed_link import LINK_TTL, SignedLinkService

logger = logging.getLogger(__name__)

EMAIL_SEVERITIES = frozenset({"critical", "high"})
MAX_ATTEMPTS = 3
# Wait after attempt n (1-based) before the next try; no wait after the last attempt.
BACKOFF = (timedelta(minutes=1), timedelta(minutes=2), timedelta(minutes=4))
SUBSCRIPTION_PENDING = "subscription_pending"
CONTACT_UNSUBSCRIBED = "contact_unsubscribed"  # final: no retries (they opted out)


def next_attempt_at(attempt_count: int, now: datetime) -> datetime | None:
    if attempt_count >= MAX_ATTEMPTS:
        return None
    return now + BACKOFF[attempt_count - 1]


@dataclass
class NotificationService:
    session: Session
    notifier: Notifier
    links: SignedLinkService
    contacts: SettingsReader
    houses: HouseReader
    clock: Callable[[], datetime] = utc_now

    @property
    def repo(self) -> NotificationRepository:
        return NotificationRepository(self.session)

    def notify(self, alert: Alert) -> list[Notification]:
        """Record the in-app notification, then email the house's contacts in priority order."""
        now = self.clock()
        rows = [
            self.repo.add(
                Notification(
                    alert_id=alert.alert_id,
                    channel="in_app",
                    status="sent",
                    attempt_count=1,
                    sent_at=now,
                )
            )
        ]
        self.session.commit()
        if alert.severity not in EMAIL_SEVERITIES:
            return rows

        try:
            contacts = self.contacts.contacts(alert.house_id)
        except DependencyUnavailableError as exc:
            # The alert is already raised and visible in-app; emails cannot be addressed.
            logger.error(
                "contacts unavailable, alert emails not sent",
                extra={"alert_id": alert.alert_id, "source": exc.source},
            )
            return rows

        for contact in contacts:
            row = self.repo.add(
                Notification(
                    alert_id=alert.alert_id,
                    contact_id=contact.contact_id,
                    channel="email",
                    recipient=contact.email,
                    priority=contact.priority,
                    status="queued",
                )
            )
            self.session.commit()
            rows.append(self.deliver(row, alert, contact))
        return rows

    def deliver(self, row: Notification, alert: Alert, contact: Contact) -> Notification:
        """One email attempt for ``row`` (also used by the retry job)."""
        try:
            topic = self.notifier.ensure_topic(alert.house_id)
            subscription = self.notifier.ensure_subscription(
                topic, contact.email, contact.contact_id
            )
            if subscription.unsubscribed:
                return self.record_failure(row, CONTACT_UNSUBSCRIBED, final=True)
            if not subscription.confirmed:
                return self.record_failure(row, SUBSCRIPTION_PENDING)
            token = self.links.issue(alert.alert_id, contact.contact_id, alert.triggered_at)
            expires = alert.triggered_at + LINK_TTL
            message = render_email(self._facts(alert, contact, self.links.link(token), expires))
            message_id = self.notifier.publish(
                topic,
                message,
                contact_id=contact.contact_id,
                alert_id=alert.alert_id,
                severity=alert.severity,
            )
        except NotifierError as exc:
            return self.record_failure(row, str(exc))
        except DependencyUnavailableError as exc:  # signing key unavailable
            return self.record_failure(row, f"{exc.source}_unavailable")

        row.status = "sent"
        row.attempt_count += 1
        row.sns_message_id = message_id
        row.sent_at = self.clock()
        row.last_error = None
        row.next_attempt_at = None
        self.session.commit()
        logger.info(
            "alert email sent",
            extra={
                "alert_id": alert.alert_id,
                "recipient": describe(contact.email),
                "priority": row.priority,
            },
        )
        return row

    def record_failure(self, row: Notification, error: str, *, final: bool = False) -> Notification:
        """Count a failed attempt on ``row`` and schedule the next one (none after the last,
        or when ``final``)."""
        row.status = "failed"
        row.attempt_count += 1
        row.last_error = error[:500]
        row.next_attempt_at = None if final else next_attempt_at(row.attempt_count, self.clock())
        self.session.commit()
        logger.warning(
            "alert email not sent",
            extra={
                "alert_id": row.alert_id,
                "recipient": describe(row.recipient or ""),
                "error": row.last_error,
                "attempt": row.attempt_count,
                "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
            },
        )
        return row

    def _facts(self, alert: Alert, contact: Contact, link: str, expires: datetime) -> EmailFacts:
        house = room = None
        try:
            house = self.houses.house(alert.house_id)
            room = self.houses.room(alert.room_id) if alert.room_id else None
        except DependencyUnavailableError:
            pass  # the email still goes out, with generic wording
        return EmailFacts(
            severity=alert.severity,
            alert_type_name=alert.alert_type.name,
            house_name=house.name if house else None,
            room_name=room.name if room else None,
            house_timezone=house.timezone if house else None,
            triggered_at=alert.triggered_at,
            top_label=alert.top_label,
            top_confidence=alert.top_confidence,
            contact_name=contact.name,
            link=link,
            link_expires_at=expires,
        )
