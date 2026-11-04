"""SnsGateway against a stubbed SNS client (exact API calls, no network)."""

from __future__ import annotations

import json

import boto3
import pytest
from app.gateways.notifier import NotifierError
from app.gateways.sns_gateway import SnsGateway, filter_policy
from app.services.email_render import EmailMessage
from botocore.stub import Stubber

HOUSE = "22222222-0000-0000-0000-0000000000a1"
TOPIC = f"arn:aws:sns:us-west-2:000000000000:homeai-house-{HOUSE}"
CONTACT = "55555555-0000-4000-8000-000000000001"
SUB = f"{TOPIC}:7f0c2a1e-0000-4000-8000-000000000001"


@pytest.fixture
def sns(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    client = boto3.client("sns", region_name="us-west-2")
    with Stubber(client) as stub:
        yield SnsGateway(client), stub
        stub.assert_no_pending_responses()


def sub(endpoint="dana@example.com", arn=SUB, protocol="email"):
    return {
        "SubscriptionArn": arn,
        "Owner": "000000000000",
        "Protocol": protocol,
        "Endpoint": endpoint,
        "TopicArn": TOPIC,
    }


def test_topic_is_created_once_and_cached(sns):
    gw, stub = sns
    stub.add_response("create_topic", {"TopicArn": TOPIC}, {"Name": f"homeai-house-{HOUSE}"})
    assert gw.ensure_topic(HOUSE) == TOPIC
    assert gw.ensure_topic(HOUSE) == TOPIC  # cached: no second call


def test_new_contact_is_subscribed_with_a_filter_policy(sns):
    gw, stub = sns
    stub.add_response("list_subscriptions_by_topic", {"Subscriptions": []}, {"TopicArn": TOPIC})
    stub.add_response(
        "subscribe",
        {"SubscriptionArn": SUB},
        {
            "TopicArn": TOPIC,
            "Protocol": "email",
            "Endpoint": "dana@example.com",
            "Attributes": {"FilterPolicy": filter_policy(CONTACT)},
            "ReturnSubscriptionArn": True,
        },
    )
    stub.add_response(
        "get_subscription_attributes",
        {"Attributes": {"PendingConfirmation": "true"}},
        {"SubscriptionArn": SUB},
    )
    s = gw.ensure_subscription(TOPIC, "dana@example.com", CONTACT)
    assert (s.confirmed, s.arn) == (False, None)


def test_new_subscription_already_confirmed_is_used(sns):
    # If SNS reports the new subscription as confirmed, use it straight away.
    gw, stub = sns
    stub.add_response("list_subscriptions_by_topic", {"Subscriptions": []}, {"TopicArn": TOPIC})
    stub.add_response("subscribe", {"SubscriptionArn": SUB}, None)
    stub.add_response(
        "get_subscription_attributes",
        {"Attributes": {"PendingConfirmation": "false", "FilterPolicy": filter_policy(CONTACT)}},
        {"SubscriptionArn": SUB},
    )
    s = gw.ensure_subscription(TOPIC, "dana@example.com", CONTACT)
    assert (s.confirmed, s.arn) == (True, SUB)


def test_pending_subscription_is_not_resubscribed(sns):
    gw, stub = sns
    stub.add_response(
        "list_subscriptions_by_topic",
        {"Subscriptions": [sub(arn="PendingConfirmation")]},
        {"TopicArn": TOPIC},
    )
    assert gw.ensure_subscription(TOPIC, "dana@example.com", CONTACT).confirmed is False


def test_confirmed_subscription_found_across_pages_case_insensitive(sns):
    gw, stub = sns
    stub.add_response(
        "list_subscriptions_by_topic",
        {"Subscriptions": [sub("other@example.com")], "NextToken": "p2"},
        {"TopicArn": TOPIC},
    )
    stub.add_response(
        "list_subscriptions_by_topic",
        {"Subscriptions": [sub("sms", protocol="sms"), sub("Dana@Example.com")]},
        {"TopicArn": TOPIC, "NextToken": "p2"},
    )
    stub.add_response(
        "get_subscription_attributes",
        {"Attributes": {"FilterPolicy": filter_policy(CONTACT)}},
        {"SubscriptionArn": SUB},
    )
    s = gw.ensure_subscription(TOPIC, "dana@example.com", CONTACT)
    assert (s.confirmed, s.arn) == (True, SUB)


def test_wrong_filter_policy_is_repaired(sns):
    gw, stub = sns
    stub.add_response(
        "list_subscriptions_by_topic", {"Subscriptions": [sub()]}, {"TopicArn": TOPIC}
    )
    stub.add_response(
        "get_subscription_attributes",
        {"Attributes": {"PendingConfirmation": "false"}},
        {"SubscriptionArn": SUB},
    )
    stub.add_response(
        "set_subscription_attributes",
        {},
        {
            "SubscriptionArn": SUB,
            "AttributeName": "FilterPolicy",
            "AttributeValue": filter_policy(CONTACT),
        },
    )
    assert gw.ensure_subscription(TOPIC, "dana@example.com", CONTACT).confirmed is True


def test_publish_targets_the_contact_by_attribute(sns):
    gw, stub = sns
    stub.add_response(
        "publish",
        {"MessageId": "m-1"},
        {
            "TopicArn": TOPIC,
            "Subject": "[HomeAI] HIGH Glass break - Maple St",
            "Message": "body",
            "MessageAttributes": {
                "contact_id": {"DataType": "String", "StringValue": CONTACT},
                "alert_id": {"DataType": "String", "StringValue": "a1"},
                "severity": {"DataType": "String", "StringValue": "high"},
            },
        },
    )
    msg = EmailMessage("[HomeAI] HIGH Glass break - Maple St", "body")
    assert gw.publish(TOPIC, msg, contact_id=CONTACT, alert_id="a1", severity="high") == "m-1"


@pytest.mark.parametrize(
    ("method", "call"),
    [
        ("create_topic", lambda gw: gw.ensure_topic(HOUSE)),
        (
            "list_subscriptions_by_topic",
            lambda gw: gw.ensure_subscription(TOPIC, "d@x.io", CONTACT),
        ),
        (
            "publish",
            lambda gw: gw.publish(
                TOPIC, EmailMessage("s", "b"), contact_id=CONTACT, alert_id="a", severity="high"
            ),
        ),
    ],
)
def test_sns_errors_become_notifier_errors(sns, method, call):
    gw, stub = sns
    stub.add_client_error(method, service_error_code="Throttling", http_status_code=400)
    with pytest.raises(NotifierError, match=f"{method} failed: Throttling"):
        call(gw)


def test_client_built_lazily_with_endpoint(monkeypatch):
    built = {}
    monkeypatch.setattr(
        "app.gateways.sns_gateway.boto3.client",
        lambda svc, **kw: built.update(svc=svc, **kw) or object(),
    )
    assert SnsGateway(region="us-west-2", endpoint_url="http://localstack:4566").sns is not None
    assert built == {
        "svc": "sns",
        "region_name": "us-west-2",
        "endpoint_url": "http://localstack:4566",
    }


def test_connection_errors_become_notifier_errors():
    from botocore.exceptions import EndpointConnectionError

    class Down:
        def create_topic(self, **_):
            raise EndpointConnectionError(endpoint_url="http://localstack:4566")

    with pytest.raises(NotifierError, match="EndpointConnectionError"):
        SnsGateway(Down()).ensure_topic(HOUSE)


# --- ContactSubscriptionSync calls ----------------------------------------------------------


def test_house_topics_across_pages_ignores_other_topics(sns):
    gw, stub = sns
    other = "arn:aws:sns:us-west-2:000000000000:billing-alerts"
    house_b = "22222222-0000-0000-0000-0000000000b1"
    stub.add_response(
        "list_topics", {"Topics": [{"TopicArn": TOPIC}, {"TopicArn": other}], "NextToken": "p2"}, {}
    )
    stub.add_response(
        "list_topics",
        {"Topics": [{"TopicArn": f"arn:aws:sns:us-west-2:000000000000:homeai-house-{house_b}"}]},
        {"NextToken": "p2"},
    )
    topics = gw.house_topics()
    assert set(topics) == {HOUSE, house_b}
    assert topics[HOUSE] == TOPIC
    assert gw.ensure_topic(HOUSE) == TOPIC  # listed topics are cached: no CreateTopic


def test_email_subscriptions_hide_the_pending_placeholder_arn(sns):
    gw, stub = sns
    stub.add_response(
        "list_subscriptions_by_topic",
        {
            "Subscriptions": [
                sub("dana@example.com"),
                sub("cam@example.com", arn="PendingConfirmation"),
                sub("+15550100", protocol="sms"),
            ]
        },
        {"TopicArn": TOPIC},
    )
    subs = gw.email_subscriptions(TOPIC)
    assert [(s.email, s.arn) for s in subs] == [
        ("dana@example.com", SUB),
        ("cam@example.com", None),
    ]


def test_unsubscribe(sns):
    gw, stub = sns
    stub.add_response("unsubscribe", {}, {"SubscriptionArn": SUB})
    gw.unsubscribe(SUB)


@pytest.mark.parametrize(
    ("method", "call"),
    [
        ("list_topics", lambda gw: gw.house_topics()),
        ("unsubscribe", lambda gw: gw.unsubscribe(SUB)),
    ],
)
def test_sync_calls_map_errors(sns, method, call):
    gw, stub = sns
    stub.add_client_error(method, service_error_code="Throttling", http_status_code=400)
    with pytest.raises(NotifierError, match=f"{method} failed: Throttling"):
        call(gw)


# --- a contact's email changed ----------------------------------------------------------------

OLD = f"{TOPIC}:0ld00000-0000-4000-8000-000000000001"
OTHER = f"{TOPIC}:07e00000-0000-4000-8000-000000000001"


def test_new_address_replaces_the_contacts_old_subscription(sns):
    gw, stub = sns
    stub.add_response(
        "list_subscriptions_by_topic",
        {
            "Subscriptions": [
                sub("dana@old.example", arn=OLD),
                sub("cam@example.com", arn=OTHER),
                sub("ned@example.com", arn="PendingConfirmation"),  # skipped: no ARN to check
            ]
        },
        {"TopicArn": TOPIC},
    )
    # Policies may come back reformatted by SNS; they are compared as JSON.
    stub.add_response(
        "get_subscription_attributes",
        {"Attributes": {"FilterPolicy": json.dumps({"contact_id": [CONTACT]}, indent=1)}},
        {"SubscriptionArn": OLD},
    )
    stub.add_response("unsubscribe", {}, {"SubscriptionArn": OLD})
    stub.add_response(
        "get_subscription_attributes",
        {"Attributes": {"FilterPolicy": filter_policy("someone-else")}},
        {"SubscriptionArn": OTHER},
    )
    stub.add_response("subscribe", {"SubscriptionArn": SUB}, None)
    stub.add_response(
        "get_subscription_attributes",
        {"Attributes": {"PendingConfirmation": "true"}},
        {"SubscriptionArn": SUB},
    )
    s = gw.ensure_subscription(TOPIC, "dana@new.example", CONTACT)
    assert s.confirmed is False


def test_unreadable_filter_policy_is_not_the_contact(sns):
    from app.gateways.sns_gateway import _policy_contact

    assert _policy_contact({"FilterPolicy": "not json"}) is None
    assert _policy_contact({"FilterPolicy": '["x"]'}) is None
    assert _policy_contact({"FilterPolicy": '{"contact_id": ["a", "b"]}'}) is None
    assert _policy_contact({}) is None
