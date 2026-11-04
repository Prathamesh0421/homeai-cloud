"""ContactSubscriptionSync (every 5 min, and ``POST /alert-rules/subscriptions/sync``).

Keeps each house's SNS topic in step with its C4 emergency contacts: every contact has an
email subscription with its ``contact_id`` filter policy, and addresses that are no longer a
contact are unsubscribed. Houses that lost all their contacts are found through their existing
topics. Pending subscriptions are only counted (SNS sends the confirmation email; a pending one
cannot be unsubscribed on AWS and lapses on its own after three days).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.gateways.notifier import Notifier, NotifierError, describe
from app.gateways.types import SettingsReader

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    topics: int = 0  # houses whose topic was synced
    subscribed: int = 0  # contacts with a confirmed subscription
    pending: int = 0  # contacts waiting for them to confirm the SNS email
    removed: int = 0  # subscriptions of former contacts that were unsubscribed
    failed: int = 0  # houses skipped because SNS failed (tried again next run)


class SubscriptionSync:
    def __init__(self, contacts: SettingsReader, notifier: Notifier):
        self.contacts = contacts
        self.notifier = notifier

    def run(self, house_id: str | None = None) -> SyncResult:
        """Sync one house, or every house with contacts or a topic. C4 down -> raises."""
        result = SyncResult()
        try:
            topics = self.notifier.house_topics()
        except NotifierError as exc:
            logger.error("subscription sync: cannot list topics", extra={"error": str(exc)})
            result.failed += 1
            return result
        houses = (
            [house_id] if house_id else sorted(set(self.contacts.contact_houses()) | set(topics))
        )
        for house in houses:
            try:
                self._sync_house(house, topics.get(house), result)
            except NotifierError as exc:
                result.failed += 1
                logger.error(
                    "subscription sync failed", extra={"house_id": house, "error": str(exc)}
                )
        logger.info("subscription sync", extra={"house_id": house_id, **vars(result)})
        return result

    def _sync_house(self, house_id: str, topic: str | None, result: SyncResult) -> None:
        contacts = self.contacts.contacts(house_id)
        if contacts:
            topic = self.notifier.ensure_topic(house_id)
        if topic is None:
            return  # no contacts and no topic: nothing to do (no empty topic is created)
        result.topics += 1

        for contact in contacts:
            sub = self.notifier.ensure_subscription(topic, contact.email, contact.contact_id)
            if sub.confirmed:
                result.subscribed += 1
            else:
                result.pending += 1
                logger.info(
                    "subscription pending confirmation",
                    extra={"house_id": house_id, "recipient": describe(contact.email)},
                )

        current = {c.email.lower() for c in contacts}
        for sub in self.notifier.email_subscriptions(topic):
            if sub.email.lower() in current:
                continue
            if sub.arn is None:
                logger.info(
                    "former contact's subscription still pending; SNS removes it",
                    extra={"house_id": house_id, "recipient": describe(sub.email)},
                )
                continue
            self.notifier.unsubscribe(sub.arn)
            result.removed += 1
            logger.info(
                "former contact unsubscribed",
                extra={"house_id": house_id, "recipient": describe(sub.email)},
            )
