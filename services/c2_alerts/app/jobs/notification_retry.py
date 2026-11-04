"""NotificationRetry (every 60 s; C2 plan §4.5): try failed alert emails again.

Each due row gets one more attempt through ``NotificationService.deliver`` (same path as the
first send, including the subscription check). Before that, the contact is re-read from C4:
- removed contact -> stop for good (``contact_removed``);
- changed email -> send to the current address;
- C4 unavailable -> leave the row for the next run without using up an attempt.
Rows of a closed alert (false_positive / resolved) stop for good (``alert_closed``), and
email rows left ``queued`` by a crash are picked up after ``STUCK_AFTER``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from app.gateways.types import DependencyUnavailableError
from app.models.orm import Alert, Notification
from app.repositories.notification_repo import NotificationRepository
from app.services.notification_service import MAX_ATTEMPTS, NotificationService

logger = logging.getLogger(__name__)

STUCK_AFTER = timedelta(minutes=5)
BATCH = 100
CLOSED = frozenset({"false_positive", "resolved"})
ALERT_CLOSED = "alert_closed"
CONTACT_REMOVED = "contact_removed"


@dataclass
class RetryResult:
    due: int = 0
    sent: int = 0
    failed: int = 0  # attempted, still failed (retried later unless out of attempts)
    stopped: int = 0  # given up for good: alert closed or contact removed
    deferred: int = 0  # C4 (or the database) unavailable: left for the next run, no attempt used
    errors: list[str] = field(default_factory=list)


class NotificationRetry:
    def __init__(self, service: NotificationService, batch: int = BATCH):
        self.service = service
        self.batch = batch

    def run(self) -> RetryResult:
        now = self.service.clock()
        rows = NotificationRepository(self.service.session).due_for_retry(
            now, stuck_before=now - STUCK_AFTER, max_attempts=MAX_ATTEMPTS, limit=self.batch
        )
        result = RetryResult(due=len(rows))
        by_house: dict[str, list[tuple[Notification, Alert]]] = defaultdict(list)
        for row, alert in rows:
            by_house[alert.house_id].append((row, alert))

        for house_id, house_rows in by_house.items():
            try:
                contacts = {c.contact_id: c for c in self.service.contacts.contacts(house_id)}
            except DependencyUnavailableError as exc:
                result.deferred += len(house_rows)
                logger.warning(
                    "contacts unavailable, retry deferred",
                    extra={"house_id": house_id, "source": exc.source, "rows": len(house_rows)},
                )
                continue
            for row, alert in house_rows:
                self._retry(row, alert, contacts, result)

        if result.due:
            logger.info(
                "notification retry run",
                extra={k: v for k, v in vars(result).items() if k != "errors"},
            )
        return result

    def _retry(self, row: Notification, alert: Alert, contacts: dict, result: RetryResult) -> None:
        try:
            if alert.status in CLOSED:
                self._stop(row, ALERT_CLOSED, result)
                return
            contact = contacts.get(row.contact_id)
            if contact is None:
                self._stop(row, CONTACT_REMOVED, result)
                return
            row.recipient = contact.email
            sent = self.service.deliver(row, alert, contact)
        except Exception as exc:  # one bad row must not stop the batch
            self.service.session.rollback()
            result.errors.append(row.notification_id)
            logger.exception(
                "notification retry error",
                extra={"notification_id": row.notification_id, "error": type(exc).__name__},
            )
            # Count it as an attempt, so a row that always breaks ends "failed" after the last
            # one instead of coming back every run (and holding a place in the batch).
            try:
                self.service.record_failure(row, f"error: {type(exc).__name__}")
                result.failed += 1
            except Exception:  # e.g. the database itself is down: the next run tries again
                self.service.session.rollback()
                result.deferred += 1
            return
        if sent.status == "sent":
            result.sent += 1
        else:
            result.failed += 1

    def _stop(self, row: Notification, reason: str, result: RetryResult) -> None:
        row.status = "failed"
        row.last_error = reason
        row.next_attempt_at = None
        self.service.session.commit()
        result.stopped += 1
        logger.info(
            "alert email given up",
            extra={
                "notification_id": row.notification_id,
                "alert_id": row.alert_id,
                "reason": reason,
            },
        )
