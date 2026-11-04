"""Amazon SNS implementation of ``Notifier`` (LocalStack locally via AWS_ENDPOINT_URL)."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.gateways.notifier import (
    TOPIC_PREFIX,
    NotifierError,
    Subscription,
    TopicSubscription,
    describe,
)
from app.services.email_render import EmailMessage

logger = logging.getLogger(__name__)

PENDING = "PendingConfirmation"


def filter_policy(contact_id: str) -> str:
    return json.dumps({"contact_id": [contact_id]})


def _policy_contact(attrs: dict[str, str]) -> str | None:
    """The contact a subscription's filter policy selects (SNS may reformat the JSON)."""
    try:
        ids = json.loads(attrs.get("FilterPolicy") or "{}").get("contact_id")
    except (ValueError, AttributeError):
        return None
    return ids[0] if isinstance(ids, list) and len(ids) == 1 else None


class SnsGateway:
    def __init__(
        self,
        client: Any | None = None,
        *,
        region: str = "us-west-2",
        endpoint_url: str | None = None,
    ):
        self._client = client
        self.region = region
        self.endpoint_url = endpoint_url or None
        self._topics: dict[str, str] = {}
        self._lock = threading.Lock()

    @property
    def sns(self) -> Any:
        if self._client is None:
            self._client = boto3.client(
                "sns", region_name=self.region, endpoint_url=self.endpoint_url
            )
        return self._client

    def _call(self, what: str, fn: Any, **kwargs: Any) -> Any:
        try:
            return fn(**kwargs)
        except (ClientError, BotoCoreError) as exc:
            code = (
                exc.response.get("Error", {}).get("Code")
                if isinstance(exc, ClientError)
                else type(exc).__name__
            )
            raise NotifierError(f"sns {what} failed: {code}") from exc

    def ensure_topic(self, house_id: str) -> str:
        """CreateTopic is idempotent; cache ARNs per process."""
        with self._lock:
            arn = self._topics.get(house_id)
        if arn:
            return arn
        arn = self._call("create_topic", self.sns.create_topic, Name=f"{TOPIC_PREFIX}{house_id}")[
            "TopicArn"
        ]
        with self._lock:
            self._topics[house_id] = arn
        return arn

    def house_topics(self) -> dict[str, str]:
        """Every ``homeai-house-<house_id>`` topic in the account (ListTopics is paginated)."""
        topics: dict[str, str] = {}
        kwargs: dict[str, Any] = {}
        while True:
            page = self._call("list_topics", self.sns.list_topics, **kwargs)
            for entry in page.get("Topics", []):
                arn = entry["TopicArn"]
                name = arn.rsplit(":", 1)[-1]
                if name.startswith(TOPIC_PREFIX):
                    topics[name.removeprefix(TOPIC_PREFIX)] = arn
            if not page.get("NextToken"):
                break
            kwargs["NextToken"] = page["NextToken"]
        with self._lock:
            self._topics.update(topics)
        return topics

    def email_subscriptions(self, topic: str) -> list[TopicSubscription]:
        return [
            TopicSubscription(
                email=sub.get("Endpoint", ""),
                arn=sub["SubscriptionArn"]
                if sub.get("SubscriptionArn", "").startswith("arn:")
                else None,
            )
            for sub in self.subscriptions(topic)
            if sub.get("Protocol") == "email"
        ]

    def unsubscribe(self, arn: str) -> None:
        self._call("unsubscribe", self.sns.unsubscribe, SubscriptionArn=arn)

    def subscriptions(self, topic: str) -> list[dict[str, Any]]:
        subs: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {"TopicArn": topic}
        while True:
            page = self._call(
                "list_subscriptions_by_topic", self.sns.list_subscriptions_by_topic, **kwargs
            )
            subs.extend(page.get("Subscriptions", []))
            if not page.get("NextToken"):
                return subs
            kwargs["NextToken"] = page["NextToken"]

    def ensure_subscription(self, topic: str, email: str, contact_id: str) -> Subscription:
        """Find the contact's email subscription (keeping its filter policy right) or create it.

        An email subscription stays pending until the contact clicks the link SNS sends them;
        until then a publish does not reach them. The state is read from SNS's
        ``PendingConfirmation`` attribute: AWS lists pending subscriptions with the ARN
        ``PendingConfirmation``, LocalStack lists them with a real ARN.
        """
        subs = [s for s in self.subscriptions(topic) if s.get("Protocol") == "email"]
        for sub in subs:
            if sub.get("Endpoint", "").lower() == email.lower():
                arn = sub.get("SubscriptionArn", "")
                if not arn or arn == PENDING:
                    return Subscription(contact_id, email, confirmed=False)
                return self._state(arn, email, contact_id)
        # A new address for this contact: the old address's subscription carries the same
        # filter policy, so it would get this contact's emails (and signed links) too.
        self._drop_previous_addresses(subs, contact_id)
        created = self._call(
            "subscribe",
            self.sns.subscribe,
            TopicArn=topic,
            Protocol="email",
            Endpoint=email,
            Attributes={"FilterPolicy": filter_policy(contact_id)},
            ReturnSubscriptionArn=True,
        )
        logger.info(
            "sns subscription requested", extra={"topic": topic, "recipient": describe(email)}
        )
        return self._state(created["SubscriptionArn"], email, contact_id)

    def _drop_previous_addresses(self, subs: list[dict[str, Any]], contact_id: str) -> None:
        for sub in subs:
            arn = sub.get("SubscriptionArn", "")
            if not arn.startswith("arn:"):
                continue  # pending on AWS: receives nothing, lapses on its own
            attrs = self._call(
                "get_subscription_attributes",
                self.sns.get_subscription_attributes,
                SubscriptionArn=arn,
            ).get("Attributes", {})
            if _policy_contact(attrs) == contact_id:
                self._call("unsubscribe", self.sns.unsubscribe, SubscriptionArn=arn)
                logger.info(
                    "previous address unsubscribed",
                    extra={"recipient": describe(sub.get("Endpoint", ""))},
                )

    def _state(self, arn: str, email: str, contact_id: str) -> Subscription:
        attrs = self._call(
            "get_subscription_attributes", self.sns.get_subscription_attributes, SubscriptionArn=arn
        ).get("Attributes", {})
        if attrs.get("PendingConfirmation", "false") == "true":
            return Subscription(contact_id, email, confirmed=False)
        if _policy_contact(attrs) != contact_id:
            self._call(
                "set_subscription_attributes",
                self.sns.set_subscription_attributes,
                SubscriptionArn=arn,
                AttributeName="FilterPolicy",
                AttributeValue=filter_policy(contact_id),
            )
        return Subscription(contact_id, email, confirmed=True, arn=arn)

    def publish(
        self, topic: str, message: EmailMessage, *, contact_id: str, alert_id: str, severity: str
    ) -> str:
        def attr(value: str) -> dict[str, str]:
            return {"DataType": "String", "StringValue": value}

        response = self._call(
            "publish",
            self.sns.publish,
            TopicArn=topic,
            Subject=message.subject,
            Message=message.body,
            MessageAttributes={
                "contact_id": attr(contact_id),
                "alert_id": attr(alert_id),
                "severity": attr(severity),
            },
        )
        return response["MessageId"]
