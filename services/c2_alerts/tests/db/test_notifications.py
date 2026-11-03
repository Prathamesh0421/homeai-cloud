"""C2-09: NotificationService with a fake notifier, and notifications through POST /evaluate."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from app.api.deps import (
    get_clock,
    get_detection_reader,
    get_house_reader,
    get_notifier,
    get_session,
    get_settings_reader,
)
from app.gateways.notifier import LogNotifier
from app.gateways.types import Contact, Detection
from app.main import create_app, make_notifier
from app.models.orm import Notification
from app.services.notification_service import NotificationService, next_attempt_at
from app.services.signed_link import KeyRing, SignedLinkService
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.factories import (
    BATH,
    HOUSE_A1,
    KITCHEN,
    MAPLE,
    ROOM_A1_KITCHEN,
    TENANT_A,
    make_alert,
    make_rule,
    uid,
)
from tests.fakes import FakeDetectionReader, FakeHouseReader, FakeNotifier, FakeSettingsReader

NOW = datetime(2026, 10, 25, 6, 12, tzinfo=UTC)
TRIGGERED = datetime(2026, 10, 25, 6, 10, tzinfo=UTC)
DANA = Contact("55555555-0000-4000-8000-000000000001", "Dana", "dana@example.com", "family", 1)
CAM = Contact("55555555-0000-4000-8000-000000000002", "Cam", "cam@example.com", "caregiver", 2)
NED = Contact("55555555-0000-4000-8000-000000000003", "Ned", "ned@example.com", "neighbor", 3)
LINKS = SignedLinkService(
    keys=lambda: KeyRing("k1", {"k1": b"k" * 32}), public_base_url="https://homeai.example"
)


@pytest.fixture
def notifier():
    return FakeNotifier()


@pytest.fixture
def contacts():
    return FakeSettingsReader(contacts={HOUSE_A1: [NED, DANA, CAM]})  # stored out of order


@pytest.fixture
def houses():
    return FakeHouseReader([MAPLE], [BATH, KITCHEN])


@pytest.fixture
def service(session, notifier, contacts, houses):
    return NotificationService(
        session=session,
        notifier=notifier,
        links=LINKS,
        contacts=contacts,
        houses=houses,
        clock=lambda: NOW,
    )


def alert_with(session, severity):
    rule = make_rule(session, "intrusion")
    return make_alert(
        session,
        rule,
        house_id=HOUSE_A1,
        room_id=ROOM_A1_KITCHEN,
        severity=severity,
        triggered_at=TRIGGERED,
    )


def emails(rows):
    return [r for r in rows if r.channel == "email"]


# --- who gets what --------------------------------------------------------------------------


@pytest.mark.parametrize("severity", ["critical", "high"])
def test_critical_and_high_email_contacts_in_priority_order(session, service, notifier, severity):
    alert = alert_with(session, severity)
    rows = service.notify(alert)
    assert (rows[0].channel, rows[0].status) == ("in_app", "sent")
    assert [(r.recipient, r.priority, r.status) for r in emails(rows)] == [
        ("dana@example.com", 1, "sent"),
        ("cam@example.com", 2, "sent"),
        ("ned@example.com", 3, "sent"),
    ]
    assert [p["contact_id"] for p in notifier.published] == [
        DANA.contact_id,
        CAM.contact_id,
        NED.contact_id,
    ]
    first = emails(rows)[0]
    assert (first.sns_message_id, first.attempt_count, first.sent_at, first.last_error) == (
        "msg-1",
        1,
        NOW,
        None,
    )
    assert notifier.published[0]["topic"].endswith(f"homeai-house-{HOUSE_A1}")
    assert (notifier.published[0]["alert_id"], notifier.published[0]["severity"]) == (
        alert.alert_id,
        severity,
    )


@pytest.mark.parametrize("severity", ["medium", "low"])
def test_medium_and_low_are_in_app_only(session, service, notifier, severity):
    rows = service.notify(alert_with(session, severity))
    assert [(r.channel, r.status) for r in rows] == [("in_app", "sent")]
    assert notifier.published == []


def test_rows_are_committed(session, service):
    alert = alert_with(session, "high")
    service.notify(alert)
    session.expire_all()
    stored = session.scalars(
        select(Notification).where(Notification.alert_id == alert.alert_id)
    ).all()
    assert len(stored) == 4


def test_email_content_and_working_link(session, service, notifier):
    alert = alert_with(session, "high")
    service.notify(alert)
    message = notifier.published[0]["message"]
    assert message.subject == "[HomeAI] HIGH Glass break - Maple St"
    assert "Hi Dana," in message.body and "Room: Kitchen" in message.body
    assert "2026-10-24 23:10 PDT" in message.body
    link = next(line for line in message.body.splitlines() if "alert-view/" in line).split(": ", 1)[
        1
    ]
    claims = LINKS.verify(link.rsplit("/", 1)[1], now=NOW)
    assert (claims.alert_id, claims.contact_id) == (alert.alert_id, DANA.contact_id)
    # Each contact gets their own link.
    assert notifier.published[1]["message"].body != message.body


# --- failures -------------------------------------------------------------------------------


def test_pending_subscription_is_failed_with_retry_in_a_minute(session, service, notifier):
    notifier.pending.add("cam@example.com")
    rows = emails(service.notify(alert_with(session, "critical")))
    cam = rows[1]
    assert (cam.status, cam.last_error, cam.attempt_count) == ("failed", "subscription_pending", 1)
    assert cam.next_attempt_at == NOW + timedelta(minutes=1)
    assert [r.status for r in rows] == ["sent", "failed", "sent"]  # others still notified


def test_publish_error_is_failed_with_retry(session, service, notifier):
    notifier.fail_publish.add(DANA.contact_id)
    dana = emails(service.notify(alert_with(session, "high")))[0]
    assert (dana.status, dana.attempt_count, dana.sns_message_id) == ("failed", 1, None)
    assert "publish failed" in dana.last_error
    assert dana.next_attempt_at == NOW + timedelta(minutes=1)


def test_topic_error_fails_each_contact(session, service, notifier):
    notifier.fail_topic = True
    rows = emails(service.notify(alert_with(session, "high")))
    assert {r.status for r in rows} == {"failed"}
    assert all("create_topic" in r.last_error for r in rows)


def test_signing_key_unavailable_fails_the_email(session, notifier, contacts, houses):
    from app.gateways.types import DependencyUnavailableError

    def no_key():
        raise DependencyUnavailableError("secrets")

    service = NotificationService(
        session=session,
        notifier=notifier,
        links=SignedLinkService(keys=no_key, public_base_url="x"),
        contacts=contacts,
        houses=houses,
        clock=lambda: NOW,
    )
    rows = emails(service.notify(alert_with(session, "high")))
    assert {(r.status, r.last_error) for r in rows} == {("failed", "secrets_unavailable")}


def test_contacts_unavailable_keeps_the_in_app_record(session, service, contacts, caplog):
    contacts.down = True
    with caplog.at_level(logging.ERROR):
        rows = service.notify(alert_with(session, "critical"))
    assert [(r.channel, r.status) for r in rows] == [("in_app", "sent")]
    assert "contacts unavailable" in caplog.text


def test_house_names_unavailable_still_sends(session, service, houses, notifier):
    houses.down = True
    rows = emails(service.notify(alert_with(session, "high")))
    assert {r.status for r in rows} == {"sent"}
    assert notifier.published[0]["message"].subject == "[HomeAI] HIGH Glass break"


def test_no_contacts_means_in_app_only(session, service, contacts, notifier):
    contacts._contacts = {}
    rows = service.notify(alert_with(session, "critical"))
    assert [r.channel for r in rows] == ["in_app"]


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(1, NOW + timedelta(minutes=1)), (2, NOW + timedelta(minutes=2)), (3, None), (4, None)],
)
def test_backoff(attempt, expected):
    assert next_attempt_at(attempt, NOW) == expected


def test_log_lines_mask_recipients(session, service, notifier, caplog):
    notifier.pending.add("dana@example.com")
    with caplog.at_level(logging.INFO):
        service.notify(alert_with(session, "high"))
    assert "dana@example.com" not in caplog.text
    assert "d***@example.com" in str([getattr(r, "recipient", "") for r in caplog.records])


# --- LogNotifier and make_notifier ----------------------------------------------------------


def test_log_notifier_writes_the_email_to_the_log(session, contacts, houses, caplog):
    service = NotificationService(
        session=session,
        notifier=LogNotifier(),
        links=LINKS,
        contacts=contacts,
        houses=houses,
        clock=lambda: NOW,
    )
    with caplog.at_level(logging.INFO, logger="app.gateways.notifier"):
        rows = emails(service.notify(alert_with(session, "critical")))
    assert {r.status for r in rows} == {"sent"}
    assert all(r.sns_message_id.startswith("log-") for r in rows)
    logged = [r for r in caplog.records if r.getMessage() == "alert email (NOTIFIER=log)"]
    assert len(logged) == 3
    assert logged[0].subject == "[HomeAI] CRITICAL Glass break - Maple St"
    assert "https://homeai.example/alert-view/" in logged[0].body


def test_make_notifier_follows_settings(settings):
    from app.gateways.sns_gateway import SnsGateway

    assert isinstance(make_notifier(settings.model_copy(update={"notifier": "log"})), LogNotifier)
    sns = make_notifier(
        settings.model_copy(
            update={"notifier": "sns", "aws_endpoint_url": "http://localstack:4566"}
        )
    )
    assert isinstance(sns, SnsGateway) and sns.endpoint_url == "http://localstack:4566"


# --- through POST /alerts/evaluate ----------------------------------------------------------


@pytest.fixture
def client(settings, session, notifier, contacts, houses):
    detections = FakeDetectionReader()
    app = create_app(settings, checks={})
    app.state.test_detections = detections
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_house_reader] = lambda: houses
    app.dependency_overrides[get_settings_reader] = lambda: contacts
    app.dependency_overrides[get_detection_reader] = lambda: detections
    app.dependency_overrides[get_notifier] = lambda: notifier
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _evaluate(client, auth_header, label="glass_break", confidence=0.78):
    d = Detection(
        _id=uid(),
        media_id=uid(),
        tenant_id=TENANT_A,
        house_id=HOUSE_A1,
        room_id=ROOM_A1_KITCHEN,
        top_label=label,
        top_confidence=confidence,
        labels=[{"label": label, "confidence": confidence}],
        detected_at=TRIGGERED,
    )
    client.app.state.test_detections.add(d)
    body = {
        "detection_id": d.detection_id,
        "media_id": d.media_id,
        "house_id": HOUSE_A1,
        "room_id": ROOM_A1_KITCHEN,
        "top_label": label,
        "top_confidence": confidence,
        "labels": [],
        "detected_at": "2026-10-25T06:10:00Z",
    }
    headers = auth_header(service_scopes=["alerts:evaluate"])
    return body, client.post("/api/v1/alerts/evaluate", json=body, headers=headers), headers


def test_evaluate_notifies_once_and_detail_shows_it(client, auth_header, session, notifier):
    make_rule(session, "intrusion")
    body, r, headers = _evaluate(client, auth_header)
    assert r.status_code == 201
    assert len(notifier.published) == 3
    # A replay is a duplicate and does not email again.
    assert (
        client.post("/api/v1/alerts/evaluate", json=body, headers=headers).json()["data"][
            "duplicate"
        ]
        is True
    )
    assert len(notifier.published) == 3

    staff = auth_header(role="cloud_staff", tenant_id=TENANT_A)
    notes = client.get(f"/api/v1/alerts/{r.json()['data']['alert_id']}", headers=staff).json()[
        "data"
    ]["notifications"]
    assert [(n["channel"], n["priority"], n["status"]) for n in notes] == [
        ("in_app", None, "sent"),
        ("email", 1, "sent"),
        ("email", 2, "sent"),
        ("email", 3, "sent"),
    ]


def test_no_alert_sends_nothing(client, auth_header, session, notifier):
    make_rule(session, "intrusion")
    _, r, _ = _evaluate(client, auth_header, confidence=0.10)
    assert r.json()["data"]["decision"] == "no_alert"
    assert notifier.published == []


def test_notification_crash_does_not_change_the_201(
    client, auth_header, session, notifier, monkeypatch
):
    make_rule(session, "intrusion")

    def boom(self, alert):
        raise RuntimeError("smtp on fire")

    monkeypatch.setattr(NotificationService, "notify", boom)
    _, r, _ = _evaluate(client, auth_header)
    assert r.status_code == 201
