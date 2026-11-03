"""C2-08: GET /alert-view/{token} (public signed link) and DEMO_MODE view_link in detail."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.api.deps import get_clock, get_detection_reader, get_house_reader, get_session
from app.gateways.types import Detection
from app.main import create_app
from app.models.orm import Notification
from app.repositories.notification_repo import NotificationRepository
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.factories import (
    BATH,
    HOUSE_A1,
    KITCHEN,
    MAPLE,
    OWNER_USER,
    ROOM_A1_KITCHEN,
    TENANT_A,
    make_alert,
    make_rule,
    uid,
)
from tests.fakes import FakeDetectionReader, FakeHouseReader

VIEW = "/api/v1/alert-view"
TRIGGERED = datetime(2026, 10, 24, 23, 10, tzinfo=UTC)
CONTACT = "55555555-0000-4000-8000-000000000001"


@pytest.fixture
def now():
    return {"value": TRIGGERED + timedelta(hours=1)}


@pytest.fixture
def make_client(settings, session, now):
    clients = []

    def _make(**settings_overrides) -> TestClient:
        app = create_app(settings.model_copy(update=settings_overrides), checks={})
        detections = FakeDetectionReader()
        app.state.test_detections = detections
        app.dependency_overrides[get_session] = lambda: session
        app.dependency_overrides[get_house_reader] = lambda: FakeHouseReader(
            [MAPLE], [BATH, KITCHEN]
        )
        app.dependency_overrides[get_detection_reader] = lambda: detections
        app.dependency_overrides[get_clock] = lambda: lambda: now["value"]
        c = TestClient(app, raise_server_exceptions=False)
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def alert(session):
    rule = make_rule(session, "intrusion")
    return make_alert(
        session,
        rule,
        house_id=HOUSE_A1,
        room_id=ROOM_A1_KITCHEN,
        severity="high",
        triggered_at=TRIGGERED,
    )


def token_for(client, alert_id, contact_id=CONTACT, triggered_at=TRIGGERED) -> str:
    return client.app.state.links.issue(alert_id, contact_id, triggered_at)


def test_view_returns_only_the_public_fields(client, alert):
    client.app.state.test_detections.add(
        Detection(
            _id=alert.detection_id,
            media_id=alert.media_id,
            tenant_id=TENANT_A,
            house_id=HOUSE_A1,
            room_id=ROOM_A1_KITCHEN,
            labels=[{"label": "glass_break", "confidence": 0.78, "source_class": "Glass"}],
            top_label="glass_break",
            top_confidence=0.78,
            detected_at=TRIGGERED,
        )
    )
    r = client.get(f"{VIEW}/{token_for(client, alert.alert_id)}")
    assert r.status_code == 200, r.text
    assert r.json()["data"] == {
        "alert_type_name": "Glass break",
        "severity": "high",
        "status": "open",
        "house_name": "Maple St",
        "room_name": "Kitchen",
        "triggered_at": "2026-10-24T23:10:00Z",
        "labels": [{"label": "glass_break", "confidence": 0.78}],
        "clip_url": None,
        "expires_at": "2026-10-25T23:10:00Z",
    }
    # No identifiers or personal data in the public page.
    for leak in (
        alert.alert_id,
        alert.tenant_id,
        HOUSE_A1,
        alert.detection_id,
        alert.media_id,
        CONTACT,
    ):
        assert leak not in r.text


def test_view_shows_the_current_status(client, alert, session):
    session.execute(
        text("UPDATE c2.alerts SET status = 'resolved' WHERE alert_id = :a"), {"a": alert.alert_id}
    )
    session.expire_all()
    assert (
        client.get(f"{VIEW}/{token_for(client, alert.alert_id)}").json()["data"]["status"]
        == "resolved"
    )


def test_expired_link_is_401(client, alert, now):
    token = token_for(client, alert.alert_id)
    now["value"] = TRIGGERED + timedelta(hours=24, seconds=1)
    r = client.get(f"{VIEW}/{token}")
    assert (r.status_code, r.json()["error"]["code"]) == (401, "token_expired")


@pytest.mark.parametrize(
    "make_token",
    [
        lambda c, a: token_for(c, a.alert_id)[:-3] + "AAA",  # signature tampered
        lambda c, a: "garbage",
        lambda c, a: token_for(c, uid()),  # genuine link, alert does not exist
    ],
)
def test_invalid_links_are_404(client, alert, make_token):
    r = client.get(f"{VIEW}/{make_token(client, alert)}")
    assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")


def test_link_signed_with_another_key_is_404(make_client, alert):
    other = make_client(alert_view_key="b3RoZXIta2V5LWZvci10ZXN0cy0wMDAwMDAwMDAwMDA=")
    token = other.app.state.links.issue(alert.alert_id, CONTACT, TRIGGERED)
    mine = make_client()
    assert mine.get(f"{VIEW}/{token}").status_code == 404


def test_needs_no_login(client, alert):
    r = client.get(
        f"{VIEW}/{token_for(client, alert.alert_id)}", headers={"Authorization": "Bearer junk"}
    )
    assert r.status_code == 200


def test_rate_limited_per_ip(make_client, alert):
    c = make_client(alert_view_rate_limit_per_min=3)
    good = token_for(c, alert.alert_id)
    assert [c.get(f"{VIEW}/{good}").status_code for _ in range(3)] == [200, 200, 200]
    r = c.get(f"{VIEW}/garbage")  # counts even before the token is checked
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["Retry-After"]) >= 1


def test_openapi_lists_public_route(client):
    assert f"{VIEW}/{{token}}" in client.get("/api/v1/docs/c2/openapi.json").json()["paths"]


# --- DEMO_MODE view_link in alert detail ----------------------------------------------------


def _email_notification(session, alert):
    NotificationRepository(session).add(
        Notification(
            alert_id=alert.alert_id,
            contact_id=CONTACT,
            channel="email",
            recipient="dana@example.com",
            priority=1,
            status="sent",
        )
    )
    NotificationRepository(session).add(
        Notification(alert_id=alert.alert_id, channel="in_app", status="sent")
    )


def test_demo_mode_adds_a_working_view_link(make_client, auth_header, session, alert):
    _email_notification(session, alert)
    c = make_client(demo_mode=True, public_base_url="http://localhost:8080")
    owner = auth_header(
        user_id=OWNER_USER, role="house_owner", tenant_id=TENANT_A, house_ids=[HOUSE_A1]
    )
    notes = c.get(f"/api/v1/alerts/{alert.alert_id}", headers=owner).json()["data"]["notifications"]
    in_app, email = notes
    assert in_app["view_link"] is None
    assert email["view_link"].startswith("http://localhost:8080/alert-view/")
    token = email["view_link"].rsplit("/", 1)[1]
    assert c.get(f"{VIEW}/{token}").json()["data"]["alert_type_name"] == "Glass break"


def test_no_view_link_outside_demo_mode(client, auth_header, session, alert):
    _email_notification(session, alert)
    owner = auth_header(
        user_id=OWNER_USER, role="house_owner", tenant_id=TENANT_A, house_ids=[HOUSE_A1]
    )
    notes = client.get(f"/api/v1/alerts/{alert.alert_id}", headers=owner).json()["data"][
        "notifications"
    ]
    assert {n["view_link"] for n in notes} == {None}


def test_demo_link_is_skipped_when_the_key_is_unavailable(
    make_client, auth_header, session, alert, monkeypatch
):
    from app.gateways.types import DependencyUnavailableError
    from app.services.signed_link import SignedLinkService

    _email_notification(session, alert)
    c = make_client(demo_mode=True)
    monkeypatch.setattr(
        SignedLinkService,
        "issue",
        lambda *a, **k: (_ for _ in ()).throw(DependencyUnavailableError("secrets")),
    )
    staff = auth_header(role="cloud_staff", tenant_id=TENANT_A)
    r = c.get(f"/api/v1/alerts/{alert.alert_id}", headers=staff)
    assert r.status_code == 200
    assert {n["view_link"] for n in r.json()["data"]["notifications"]} == {None}
