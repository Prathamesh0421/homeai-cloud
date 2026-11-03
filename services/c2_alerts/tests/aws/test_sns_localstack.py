"""SnsGateway against real SNS in LocalStack (CI runs LocalStack; locally it skips without it)."""

from __future__ import annotations

import json
import os
import time
import uuid

import boto3
import pytest
from app.gateways.sns_gateway import SnsGateway
from app.services.email_render import EmailMessage
from botocore.config import Config

ENDPOINT = os.environ.get("AWS_ENDPOINT_URL")


def _unavailable(reason: str) -> None:
    if os.environ.get("CI") == "true":
        pytest.fail(f"LocalStack SNS required on CI: {reason}", pytrace=False)
    pytest.skip(reason)


@pytest.fixture(scope="module")
def sns_client():
    if not ENDPOINT:
        _unavailable("AWS_ENDPOINT_URL not set")
    client = boto3.client(
        "sns",
        region_name=os.environ.get("AWS_REGION", "us-west-2"),
        endpoint_url=ENDPOINT,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 1}),
    )
    deadline = time.monotonic() + 60  # CI's LocalStack container has no healthcheck
    while True:
        try:
            client.list_topics()
            return client
        except Exception as exc:
            if time.monotonic() > deadline:
                _unavailable(f"LocalStack not reachable at {ENDPOINT}: {type(exc).__name__}")
            time.sleep(2)


@pytest.fixture
def house():
    return str(uuid.uuid4())


def test_topic_is_idempotent_across_instances(sns_client, house):
    arn = SnsGateway(sns_client).ensure_topic(house)
    assert arn.endswith(f":homeai-house-{house}")
    assert SnsGateway(sns_client).ensure_topic(house) == arn


def test_subscription_is_created_once_with_its_filter_policy(sns_client, house):
    gw = SnsGateway(sns_client)
    topic = gw.ensure_topic(house)
    contact = str(uuid.uuid4())
    first = gw.ensure_subscription(topic, "dana@example.com", contact)
    second = gw.ensure_subscription(topic, "Dana@Example.com", contact)
    # Email subscriptions start pending (nobody clicked the confirmation link).
    assert (first.confirmed, second.confirmed) == (False, False)

    subs = [s for s in gw.subscriptions(topic) if s["Protocol"] == "email"]
    assert len(subs) == 1
    arn = subs[0]["SubscriptionArn"]
    if arn != "PendingConfirmation":  # LocalStack exposes the ARN, so the policy is checkable
        attrs = sns_client.get_subscription_attributes(SubscriptionArn=arn)["Attributes"]
        assert json.loads(attrs["FilterPolicy"]) == {"contact_id": [contact]}


def test_publish_returns_a_message_id(sns_client, house):
    gw = SnsGateway(sns_client)
    topic = gw.ensure_topic(house)
    message_id = gw.publish(
        topic,
        EmailMessage("[HomeAI] HIGH Glass break - Maple St", "body"),
        contact_id=str(uuid.uuid4()),
        alert_id=str(uuid.uuid4()),
        severity="high",
    )
    assert message_id
