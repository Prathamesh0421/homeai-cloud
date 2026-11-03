"""C2-06: alerts list, stats, detail and lifecycle actions against Postgres.

C1 houses/rooms and C3 detections come from the fakes; tokens from a static test JWKS.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.api.deps import get_detection_reader, get_house_reader, get_session
from app.gateways.types import Detection
from app.main import create_app
from app.models.orm import Notification
from app.repositories.alert_repo import AlertRepository
from app.repositories.history_repo import HistoryRepository
from app.repositories.notification_repo import NotificationRepository
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.factories import (
    BATH,
    HOUSE_A1,
    HOUSE_A2,
    HOUSE_B1,
    KITCHEN,
    MAPLE,
    OAK,
    OWNER_USER,
    PINE,
    ROOM_A1_BATH,
    ROOM_A1_KITCHEN,
    STAFF_USER,
    TENANT_A,
    TENANT_B,
    make_alert,
    make_rule,
    uid,
)
from tests.fakes import FakeDetectionReader, FakeHouseReader

ALERTS = "/api/v1/alerts"
T0 = datetime(2026, 10, 24, 18, 40, tzinfo=UTC)


@pytest.fixture
def houses():
    return FakeHouseReader([MAPLE, OAK, PINE], [BATH, KITCHEN])


@pytest.fixture
def detections():
    return FakeDetectionReader()


@pytest.fixture
def client(settings, session, houses, detections):
    app = create_app(settings, checks={})
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_house_reader] = lambda: houses
    app.dependency_overrides[get_detection_reader] = lambda: detections
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def who(client, auth_header):
    """Headers for each kind of caller."""
    return {
        "owner_a1": auth_header(
            user_id=OWNER_USER, role="house_owner", tenant_id=TENANT_A, house_ids=[HOUSE_A1]
        ),
        "owner_b1": auth_header(
            user_id=uid(), role="house_owner", tenant_id=TENANT_B, house_ids=[HOUSE_B1]
        ),
        "staff": auth_header(user_id=STAFF_USER, role="cloud_staff", tenant_id=TENANT_A),
        "iot": auth_header(user_id=uid(), role="iot_staff", tenant_id=TENANT_A),
        "c4": auth_header(service_scopes=["alerts:read"]),
        "c3": auth_header(service_scopes=["alerts:evaluate"]),
    }


@pytest.fixture
def seeded(session):
    """Four alerts: Maple x3 (two types), Oak x1, Pine (tenant B) x1."""
    intrusion = make_rule(session, "intrusion")
    fall = make_rule(session, "fall")
    pine_rule = make_rule(session, "intrusion", tenant_id=TENANT_B)
    return {
        "maple_glass": make_alert(
            session,
            intrusion,
            house_id=HOUSE_A1,
            room_id=ROOM_A1_KITCHEN,
            severity="high",
            triggered_at=T0,
        ),
        "maple_fall": make_alert(
            session,
            fall,
            house_id=HOUSE_A1,
            room_id=ROOM_A1_BATH,
            severity="high",
            status="acknowledged",
            triggered_at=T0 + timedelta(hours=1),
        ),
        "maple_critical": make_alert(
            session,
            intrusion,
            house_id=HOUSE_A1,
            severity="critical",
            triggered_at=T0 + timedelta(hours=2),
        ),
        "oak": make_alert(
            session,
            intrusion,
            house_id=HOUSE_A2,
            severity="medium",
            status="resolved",
            triggered_at=T0 + timedelta(days=1),
        ),
        "pine": make_alert(session, pine_rule, house_id=HOUSE_B1, severity="low", triggered_at=T0),
    }


def ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [a["alert_id"] for a in response.json()["data"]]


def field_issue(response) -> dict[str, str]:
    assert response.status_code == 422, response.text
    return {d["field"]: d["issue"] for d in response.json()["error"]["details"]}


# --- list -----------------------------------------------------------------------------------


def test_owner_sees_only_their_houses_newest_first(client, who, seeded):
    r = client.get(ALERTS, headers=who["owner_a1"])
    assert ids(r) == [seeded[k].alert_id for k in ("maple_critical", "maple_fall", "maple_glass")]
    first = r.json()["data"][2]
    assert first == {
        "alert_id": seeded["maple_glass"].alert_id,
        "tenant_id": TENANT_A,
        "house_id": HOUSE_A1,
        "house_name": "Maple St",
        "room_id": ROOM_A1_KITCHEN,
        "room_name": "Kitchen",
        "alert_type_code": "intrusion",
        "alert_type_name": "Glass break",
        "category": "security",
        "severity": "high",
        "status": "open",
        "top_label": "glass_break",
        "top_confidence": 0.78,
        "triggered_at": "2026-10-24T18:40:00Z",
    }
    assert r.json()["meta"] == {"page": 1, "page_size": 25, "total": 3}


def test_tenant_b_owner_never_sees_tenant_a(client, who, seeded):
    assert ids(client.get(ALERTS, headers=who["owner_b1"])) == [seeded["pine"].alert_id]
    # Naming tenant A's house or tenant explicitly changes nothing.
    assert ids(client.get(ALERTS, params={"house_id": HOUSE_A1}, headers=who["owner_b1"])) == []
    assert ids(client.get(ALERTS, params={"tenant_id": TENANT_A}, headers=who["owner_b1"])) == [
        seeded["pine"].alert_id
    ]


def test_cloud_staff_and_c4_see_all_tenants_with_filters(client, who, seeded):
    for caller in ("staff", "c4"):
        assert len(ids(client.get(ALERTS, headers=who[caller]))) == 5
    staff = who["staff"]

    def got(**params):
        return set(ids(client.get(ALERTS, params=params, headers=staff)))

    assert got(tenant_id=TENANT_B) == {seeded["pine"].alert_id}
    assert got(status="open,acknowledged", tenant_id=TENANT_A) == {
        seeded[k].alert_id for k in ("maple_glass", "maple_fall", "maple_critical")
    }
    assert got(severity="critical") == {seeded["maple_critical"].alert_id}
    assert got(alert_type_code="fall") == {seeded["maple_fall"].alert_id}
    assert got(house_id=HOUSE_A2) == {seeded["oak"].alert_id}
    # from inclusive / to exclusive; naive times are UTC; Z and offsets work too.
    assert got(**{"from": "2026-10-24T19:40:00", "to": "2026-10-24T20:40:00Z"}) == {
        seeded["maple_fall"].alert_id
    }
    assert got(**{"from": "2026-10-24T11:40:00-07:00", "to": "2026-10-24T18:41:00Z"}) == {
        seeded["maple_glass"].alert_id,
        seeded["pine"].alert_id,
    }


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"status": "open,closed"}, "status"),
        ({"severity": "urgent"}, "severity"),
        ({"house_id": "x"}, "house_id"),
        ({"from": "2026-10-25T00:00:00Z", "to": "2026-10-24T00:00:00Z"}, "from"),
        ({"from": "yesterday"}, "from"),
        ({"page_size": 101}, "page_size"),
    ],
)
def test_list_validation(client, who, params, field):
    assert field in field_issue(client.get(ALERTS, params=params, headers=who["staff"]))


@pytest.mark.parametrize(("caller", "status"), [("iot", 403), ("c3", 403), (None, 401)])
def test_list_rejects_other_callers(client, who, caller, status):
    headers = who[caller] if caller else {}
    assert client.get(ALERTS, headers=headers).status_code == status


def test_names_are_null_when_c1_is_down(client, who, seeded, houses):
    houses.down = True
    r = client.get(ALERTS, headers=who["owner_a1"])
    assert r.status_code == 200
    assert {(a["house_name"], a["room_name"]) for a in r.json()["data"]} == {(None, None)}


# --- stats ----------------------------------------------------------------------------------

WINDOW = {"from": "2026-10-24T00:00:00Z", "to": "2026-10-26T00:00:00Z"}


def stats(client, headers, **params):
    r = client.get(f"{ALERTS}/stats", params={**WINDOW, **params}, headers=headers)
    assert r.status_code == 200, r.text
    return [(b["key"], b["count"]) for b in r.json()["data"]]


def test_stats_by_each_grouping(client, who, seeded):
    staff = who["staff"]
    assert stats(client, staff, group_by="severity") == [
        ("critical", 1),
        ("high", 2),
        ("medium", 1),
        ("low", 1),
    ]
    assert stats(client, staff, group_by="alert_type") == [("intrusion", 4), ("fall", 1)]
    assert stats(client, staff, group_by="house") == [(HOUSE_A1, 3), (HOUSE_A2, 1), (HOUSE_B1, 1)]
    assert stats(client, staff, group_by="day") == [("2026-10-24", 4), ("2026-10-25", 1)]


def test_stats_scope_and_filters(client, who, seeded):
    assert stats(client, who["owner_a1"], group_by="severity") == [("critical", 1), ("high", 2)]
    assert stats(client, who["owner_b1"], group_by="severity") == [("low", 1)]
    assert stats(client, who["c4"], group_by="severity", tenant_id=TENANT_B) == [("low", 1)]
    assert stats(client, who["staff"], group_by="severity", house_id=HOUSE_A1, status="open") == [
        ("critical", 1),
        ("high", 1),
    ]
    # to is exclusive: the Oak alert at 2026-10-25T18:40 is outside this window.
    r = client.get(
        f"{ALERTS}/stats",
        params={"group_by": "house", "from": "2026-10-24T00:00:00Z", "to": "2026-10-25T18:40:00Z"},
        headers=who["staff"],
    )
    assert HOUSE_A2 not in {b["key"] for b in r.json()["data"]}


def test_stats_day_is_utc(client, who, session):
    rule = make_rule(session, "pet")
    make_alert(session, rule, triggered_at=datetime(2026, 10, 24, 23, 30, tzinfo=UTC))
    assert stats(client, who["staff"], group_by="day") == [("2026-10-24", 1)]


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"group_by": "room", **WINDOW}, "group_by"),
        ({"group_by": "severity", "to": WINDOW["to"]}, "from"),
        ({"group_by": "severity", "from": WINDOW["from"]}, "to"),
        (
            {"group_by": "severity", "from": "2025-01-01T00:00:00Z", "to": "2026-01-03T00:00:00Z"},
            "to",
        ),
        ({"group_by": "severity", "from": WINDOW["to"], "to": WINDOW["from"]}, "from"),
        ({"group_by": "severity", "status": "gone", **WINDOW}, "status"),
    ],
)
def test_stats_validation(client, who, params, field):
    assert field in field_issue(client.get(f"{ALERTS}/stats", params=params, headers=who["staff"]))


def test_stats_rejects_other_callers(client, who):
    url = f"{ALERTS}/stats"
    params = {"group_by": "severity", **WINDOW}
    assert client.get(url, params=params, headers=who["iot"]).status_code == 403
    assert client.get(url, params=params, headers=who["c3"]).status_code == 403
    assert client.get(url, params=params).status_code == 401


# --- detail ---------------------------------------------------------------------------------


def _store_detection(detections, alert):
    detections.add(
        Detection(
            _id=alert.detection_id,
            media_id=alert.media_id,
            tenant_id=alert.tenant_id,
            house_id=alert.house_id,
            room_id=alert.room_id,
            model={"model_id": uid(), "name": "yamnet", "version": "1.0.0"},
            labels=[
                {
                    "label": "glass_break",
                    "confidence": 0.78,
                    "source_class": "Glass",
                    "start_s": 2.9,
                    "end_s": 4.8,
                },
                {"label": "speech", "confidence": 0.41},
            ],
            top_label="glass_break",
            top_confidence=0.78,
            detected_at=T0,
        )
    )


def test_detail_has_evidence_timeline_notifications_and_actions(client, who, session, detections):
    rule = make_rule(session, "intrusion")
    alert = make_alert(
        session, rule, house_id=HOUSE_A1, room_id=ROOM_A1_KITCHEN, threshold=0.45, triggered_at=T0
    )
    HistoryRepository(session).add(alert.alert_id, None, "open", "system", "system")
    NotificationRepository(session).add(
        Notification(alert_id=alert.alert_id, channel="in_app", status="sent")
    )
    NotificationRepository(session).add(
        Notification(
            alert_id=alert.alert_id,
            channel="email",
            contact_id=uid(),
            recipient="dana@example.com",
            priority=1,
            status="failed",
            attempt_count=1,
            last_error="subscription_pending",
        )
    )
    _store_detection(detections, alert)

    r = client.get(f"{ALERTS}/{alert.alert_id}", headers=who["owner_a1"])
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert (d["house_name"], d["room_name"], d["status"]) == ("Maple St", "Kitchen", "open")
    assert d["allowed_actions"] == ["acknowledge", "false_positive"]
    assert d["evidence"]["detection_available"] is True
    assert d["evidence"]["threshold"] == 0.45
    assert d["evidence"]["model"]["version"] == "1.0.0"
    assert [lbl["label"] for lbl in d["evidence"]["labels"]] == ["glass_break", "speech"]
    assert d["timeline"][0] | {"changed_at": None} == {
        "from_status": None,
        "to_status": "open",
        "actor_id": "system",
        "actor_role": "system",
        "note": None,
        "changed_at": None,
    }
    assert [(n["channel"], n["status"]) for n in d["notifications"]] == [
        ("in_app", "sent"),
        ("email", "failed"),
    ]
    assert d["notifications"][1]["last_error"] == "subscription_pending"


@pytest.mark.parametrize("problem", ["unconfigured", "down", "missing"])
def test_detail_evidence_falls_back_to_the_alert(client, who, session, detections, problem):
    alert = make_alert(session, make_rule(session, "intrusion"), house_id=HOUSE_A1)
    if problem == "unconfigured":
        client.app.dependency_overrides[get_detection_reader] = lambda: None
    elif problem == "down":
        detections.down = True
    r = client.get(f"{ALERTS}/{alert.alert_id}", headers=who["staff"])
    ev = r.json()["data"]["evidence"]
    assert ev["detection_available"] is False
    assert ev["labels"] == [
        {
            "label": "glass_break",
            "confidence": 0.78,
            "source_class": None,
            "start_s": None,
            "end_s": None,
        }
    ]
    assert ev["model"] is None


def test_detail_access(client, who, seeded):
    url = f"{ALERTS}/{seeded['maple_glass'].alert_id}"
    assert client.get(url, headers=who["owner_a1"]).status_code == 200
    assert client.get(url, headers=who["staff"]).status_code == 200
    for caller in ("owner_b1", "iot", "c4", "c3"):
        r = client.get(url, headers=who[caller])
        assert (r.status_code, r.json()["error"]["code"]) == (403, "forbidden"), caller
    assert client.get(f"{ALERTS}/{uid()}", headers=who["staff"]).status_code == 404
    assert "alert_id" in field_issue(client.get(f"{ALERTS}/nope", headers=who["staff"]))


# --- actions --------------------------------------------------------------------------------

ACTION_PATH = {
    "acknowledge": "acknowledge",
    "resolve": "resolve",
    "false_positive": "false-positive",
}
TARGET = {"acknowledge": "acknowledged", "resolve": "resolved", "false_positive": "false_positive"}
VALID = {
    ("open", "acknowledge"),
    ("acknowledged", "resolve"),
    ("open", "false_positive"),
    ("acknowledged", "false_positive"),
}


@pytest.mark.parametrize("status", ["open", "acknowledged", "resolved", "false_positive"])
@pytest.mark.parametrize("action", ["acknowledge", "resolve", "false_positive"])
def test_every_transition_over_http(client, who, session, status, action):
    alert = make_alert(session, make_rule(session, "intrusion"), house_id=HOUSE_A1, status=status)
    body = {"reason": "the cat"} if action == "false_positive" else None
    r = client.post(
        f"{ALERTS}/{alert.alert_id}/{ACTION_PATH[action]}", json=body, headers=who["owner_a1"]
    )
    if (status, action) in VALID:
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == TARGET[action]
    else:
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "invalid_state"
        assert r.json()["error"]["details"] == {"from": status, "to": TARGET[action]}


def test_acknowledge_then_resolve_records_history(client, who, session):
    alert = make_alert(session, make_rule(session, "intrusion"), house_id=HOUSE_A1)
    HistoryRepository(session).add(alert.alert_id, None, "open", "system", "system")
    url = f"{ALERTS}/{alert.alert_id}"

    ack = client.post(
        f"{url}/acknowledge", json={"note": "  on my way  "}, headers=who["owner_a1"]
    ).json()["data"]
    assert ack["status"] == "acknowledged"
    assert ack["acknowledged_at"] is not None and ack["resolved_at"] is None
    assert ack["allowed_actions"] == ["resolve", "false_positive"]

    done = client.post(f"{url}/resolve", headers=who["staff"]).json()["data"]
    assert done["status"] == "resolved" and done["resolved_at"] is not None
    assert done["allowed_actions"] == []
    assert [
        (t["from_status"], t["to_status"], t["actor_id"], t["actor_role"], t["note"])
        for t in done["timeline"]
    ] == [
        (None, "open", "system", "system", None),
        ("open", "acknowledged", OWNER_USER, "house_owner", "on my way"),
        ("acknowledged", "resolved", STAFF_USER, "cloud_staff", None),
    ]


def test_false_positive_needs_a_reason(client, who, session):
    alert = make_alert(session, make_rule(session, "intrusion"), house_id=HOUSE_A1)
    url = f"{ALERTS}/{alert.alert_id}/false-positive"
    assert "reason" in field_issue(client.post(url, json={}, headers=who["owner_a1"]))
    assert "reason" in field_issue(
        client.post(url, json={"reason": "   "}, headers=who["owner_a1"])
    )
    assert "reason" in field_issue(
        client.post(url, json={"reason": "x" * 501}, headers=who["owner_a1"])
    )
    assert "body" in field_issue(client.post(url, headers=who["owner_a1"]))

    r = client.post(url, json={"reason": "the cat knocked a glass over"}, headers=who["owner_a1"])
    d = r.json()["data"]
    assert (d["status"], d["resolved_at"] is not None) == ("false_positive", True)
    assert d["timeline"][-1]["note"] == "the cat knocked a glass over"


def test_note_validation(client, who, session):
    alert = make_alert(session, make_rule(session, "intrusion"), house_id=HOUSE_A1)
    url = f"{ALERTS}/{alert.alert_id}/acknowledge"
    assert "note" in field_issue(
        client.post(url, json={"note": "x" * 501}, headers=who["owner_a1"])
    )
    assert "extra" in field_issue(client.post(url, json={"extra": 1}, headers=who["owner_a1"]))
    # A blank note is stored as no note.
    d = client.post(url, json={"note": "  "}, headers=who["owner_a1"]).json()["data"]
    assert d["timeline"][-1]["note"] is None


def test_action_access(client, who, seeded):
    url = f"{ALERTS}/{seeded['maple_glass'].alert_id}/acknowledge"
    for caller in ("owner_b1", "iot", "c4", "c3"):
        assert client.post(url, headers=who[caller]).status_code == 403, caller
    assert client.post(url).status_code == 401
    assert client.post(f"{ALERTS}/{uid()}/acknowledge", headers=who["staff"]).status_code == 404
    # A tenant A owner of another house cannot act either.
    oak_url = f"{ALERTS}/{seeded['oak'].alert_id}/false-positive"
    assert client.post(oak_url, json={"reason": "x"}, headers=who["owner_a1"]).status_code == 403


def test_lost_race_reports_the_current_status(client, who, session, monkeypatch):
    alert = make_alert(session, make_rule(session, "intrusion"), house_id=HOUSE_A1)

    def someone_else_wins(self, alert_id, from_status, to_status, at=None):
        session.execute(
            text("UPDATE c2.alerts SET status = 'false_positive' WHERE alert_id = :a"),
            {"a": alert_id},
        )
        return False

    monkeypatch.setattr(AlertRepository, "transition", someone_else_wins)
    r = client.post(f"{ALERTS}/{alert.alert_id}/acknowledge", headers=who["owner_a1"])
    assert r.status_code == 409
    assert r.json()["error"]["details"] == {"from": "false_positive", "to": "acknowledged"}


def test_openapi_route_order(client):
    paths = list(client.get("/api/v1/docs/c2/openapi.json").json()["paths"])
    assert paths.index(f"{ALERTS}/stats") < paths.index(f"{ALERTS}/{{alert_id}}")
