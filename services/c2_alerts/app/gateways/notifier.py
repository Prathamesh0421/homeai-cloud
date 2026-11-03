"""Where alert emails go: Amazon SNS (``NOTIFIER=sns``) or the log (``NOTIFIER=log``, local).

One SNS topic per house (``homeai-house-<house_id>``); each emergency contact is an email
subscription with filter policy ``{"contact_id": [<id>]}``, and every publish carries
``contact_id``, so each contact receives only their own message (with their own signed link).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Protocol

from homeai_common.logging import mask_email

from app.services.email_render import EmailMessage

logger = logging.getLogger(__name__)

TOPIC_PREFIX = "homeai-house-"


class NotifierError(Exception):
    """Publishing or subscription management failed (the notification is retried)."""


@dataclass(frozen=True)
class Subscription:
    contact_id: str
    email: str
    confirmed: bool  # False while SNS waits for the contact to click the confirmation email
    arn: str | None = None


class Notifier(Protocol):
    def ensure_topic(self, house_id: str) -> str: ...

    def ensure_subscription(self, topic: str, email: str, contact_id: str) -> Subscription: ...

    def publish(
        self, topic: str, message: EmailMessage, *, contact_id: str, alert_id: str, severity: str
    ) -> str: ...


class LogNotifier:
    """Local stand-in for SNS: every subscription is confirmed; emails go to the log."""

    def ensure_topic(self, house_id: str) -> str:
        return f"log:{TOPIC_PREFIX}{house_id}"

    def ensure_subscription(self, topic: str, email: str, contact_id: str) -> Subscription:
        return Subscription(
            contact_id=contact_id, email=email, confirmed=True, arn=f"{topic}:{contact_id}"
        )

    def publish(
        self, topic: str, message: EmailMessage, *, contact_id: str, alert_id: str, severity: str
    ) -> str:
        message_id = f"log-{uuid.uuid4()}"
        logger.info(
            "alert email (NOTIFIER=log)",
            extra={
                "topic": topic,
                "contact_id": contact_id,
                "alert_id": alert_id,
                "severity": severity,
                "message_id": message_id,
                "subject": message.subject,
                "body": message.body,
            },
        )
        return message_id


def describe(email: str) -> str:
    """Masked recipient for log lines (contracts §6: never log full emails)."""
    return mask_email(email) or ""
