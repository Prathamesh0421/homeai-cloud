"""C2-07: POST /alerts/evaluate (contract 02 §4.3) against Postgres, with C1/C3/C4 faked."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, time

import pytest
from app.api.deps import (
    get_clock,
    get_detection_reader,
    get_house_reader,
    get_session,
    get_settings_reader,
)
from app.constants import SERVICE_CODES
from app.gateways.types import Detection, HouseSettings
from app.main import create_app
from app.models.orm import Alert, AlertRule
from app.repositories.alert_repo import AlertRepository
from app.repositories.history_repo import HistoryRepository
from app.repositories.rule_repo import RuleRepository
from app.schemas.evaluate import EvaluateRequest
from app.services.evaluate_service import evaluate_detection
from app.services.lifecycle import AlertLifecycleService
from app.services.rule_engine import RuleEngine
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from tests.factories import (
    BATH,
    HOUSE_A1,
    HOUSE_A2,
    KITCHEN,
    MAPLE,
    OAK,
    OWNER_USER,
    ROOM_A1_KITCHEN,
    STAFF_USER,
    TENANT_A,
    alert_type,
    make_rule,
    uid,
)
from tests.fakes import FakeDetectionReader, FakeHouseReader, FakeSettingsReader

URL = "/api/v1/alerts/evaluate"
NOON_LA = datetime(2026, 10, 25, 19, 0, tzinfo=UTC)
NIGHT_LA = datetime(2026, 10, 25, 6, 10, tzinfo=UTC)  # 23:10 at Maple St
MAPLE_SETTINGS = HouseSettings(
    house_id=HOUSE_A1,
    tenant_id=TENANT_A,
    enabled_services=frozenset(set(SERVICE_CODES) - {"pet"}),
    quiet_start=time(22, 0),
    quiet_end=time(7, 0),
    sensitivity="medium",
)


@pytest.fixture
def readers():
    return {
        "detections": FakeDetectionReader(),
        "houses": FakeHouseReader([MAPLE, OAK], [BATH, KITCHEN]),
        "settings": FakeSettingsReader([MAPLE_SETTINGS]),
        "now": {"value": NOON_LA},
    }


@pytest.fixture
def client(settings, session, readers):
    app = create_app(settings, checks={})
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_house_reader] = lambda: readers["houses"]
    app.dependency_overrides[get_settings_reader] = lambda: readers["settings"]
    app.dependency_overrides[get_detection_reader] = lambda: readers["detections"]
    app.dependency_overrides[get_clock] = lambda: lambda: readers["now"]["value"]
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def c3(client, auth_header):
    return auth_header(service_scopes=["alerts:evaluate"])


def detection(label="glass_break", confidence=0.78, **overrides) -> Detection:
    body = {
        "_id": uid(),
        "media_id": uid(),
        "tenant_id": TENANT_A,
        "house_id": HOUSE_A1,
        "room_id": ROOM_A1_KITCHEN,
        "model": {"model_id": uid(), "name": "yamnet", "version": "1.0.0"},
        "labels": [{"label": label, "confidence": confidence, "source_class": "Glass"}],
        "top_label": label,
        "top_confidence": confidence,
        "detected_at": datetime(2026, 10, 24, 18, 40, 50, tzinfo=UTC),
    }
    body.update(overrides)
    return Detection.model_validate(body)


def payload(d: Detection, **overrides) -> dict:
    """The contract §4.3 request body C3 sends for a stored detection."""
    body = {
        "detection_id": d.detection_id,
        "media_id": d.media_id,
        "house_id": d.house_id,
        "room_id": d.room_id,
        "top_label": d.top_label,
        "top_confidence": d.top_confidence,
        "labels": [{"label": d.top_label, "confidence": d.top_confidence}],
        "detected_at": "2026-10-24T18:40:50Z",
    }
    body.update(overrides)
    return body


def stored(readers, **kw) -> Detection:
    d = detection(**kw)
    readers["detections"].add(d)
    return d


# --- contract responses ---------------------------------------------------------------------


def test_alert_is_201_with_contract_body(client, c3, session, readers):
    make_rule(session, "intrusion")
    d = stored(readers)
    r = client.post(URL, json=payload(d), headers=c3)
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert set(data) == {"decision", "alert_id", "severity", "duplicate"}
    assert (data["decision"], data["severity"], data["duplicate"]) == ("alert", "high", False)

    alert = session.get(Alert, data["alert_id"])
    assert (alert.detection_id, alert.media_id, alert.threshold, alert.status) == (
        d.detection_id,
        d.media_id,
        0.55,
        "open",
    )
    assert [h.to_status for h in HistoryRepository(session).list_for_alert(alert.alert_id)] == [
        "open"
    ]


def test_replay_is_200_duplicate_with_the_same_alert(client, c3, session, readers):
    make_rule(session, "intrusion")
    d = stored(readers)
    first = client.post(URL, json=payload(d), headers=c3).json()["data"]
    r = client.post(URL, json=payload(d), headers=c3)
    assert r.status_code == 200
    assert r.json() == {
        "data": {"decision": "alert", "alert_id": first["alert_id"], "duplicate": True}
    }
    count = session.scalar(
        select(func.count()).select_from(Alert).where(Alert.detection_id == d.detection_id)
    )
    assert count == 1


@pytest.mark.parametrize(
    ("setup", "kw", "reason"),
    [
        (lambda s: make_rule(s, "intrusion"), {"confidence": 0.30}, "below_threshold"),
        (
            lambda s: make_rule(s, "intrusion"),
            {"label": "speech", "confidence": 0.9},
            "no_rule_match",
        ),
        (lambda s: make_rule(s, "pet"), {"label": "dog", "confidence": 0.9}, "service_disabled"),
        (
            lambda s: make_rule(s, "fall", house_id=HOUSE_A1, room_id=BATH.room_id),
            {"label": "fall_indicator", "confidence": 0.9},
            "room_mismatch",
        ),
    ],
)
def test_no_alert_is_200_with_reason(client, c3, session, readers, setup, kw, reason):
    setup(session)
    d = stored(readers, **kw)
    r = client.post(URL, json=payload(d), headers=c3)
    assert (r.status_code, r.json()) == (200, {"data": {"decision": "no_alert", "reason": reason}})
    assert session.scalar(select(func.count()).select_from(Alert)) == 0


def test_quiet_hours_hold_low_but_not_high(client, c3, session, readers):
    # Demo 10.1 step 5 / I-3: at 23:10 a cough is held, a glass break still alerts.
    make_rule(session, "wellness_cough")
    make_rule(session, "intrusion")
    readers["now"]["value"] = NIGHT_LA
    cough = stored(readers, label="cough", confidence=0.80)
    assert client.post(URL, json=payload(cough), headers=c3).json() == {
        "data": {"decision": "no_alert", "reason": "quiet_hours"}
    }
    glass = client.post(URL, json=payload(stored(readers)), headers=c3)
    assert (glass.status_code, glass.json()["data"]["severity"]) == (201, "high")


def test_contract_example_body_is_accepted(client, c3, session, readers):
    # Extra fields from a newer C3 are ignored; room_id may be null.
    make_rule(session, "intrusion")
    d = stored(readers, room_id=None)
    body = payload(d, room_id=None, model_version="1.1.0")
    assert client.post(URL, json=body, headers=c3).status_code == 201


# --- errors ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("make_body", "field"),
    [
        (lambda d: payload(d, detection_id=uid()), "detection_id"),  # not in ai_detections
        (lambda d: payload(d, house_id=HOUSE_A2), "house_id"),  # stored doc is for Maple St
        (lambda d: {k: v for k, v in payload(d).items() if k != "detection_id"}, "detection_id"),
        (lambda d: payload(d, top_confidence=1.5), "top_confidence"),
        (lambda d: payload(d, media_id="nope"), "media_id"),
        (lambda d: payload(d, detected_at="soon"), "detected_at"),
    ],
)
def test_bad_requests_are_422(client, c3, readers, make_body, field):
    d = stored(readers)
    r = client.post(URL, json=make_body(d), headers=c3)
    assert r.status_code == 422, r.text
    assert field in {x["field"] for x in r.json()["error"]["details"]}


@pytest.mark.parametrize("source", ["detections", "houses", "settings"])
def test_a_source_down_is_503_so_c3_retries(client, c3, session, readers, source):
    make_rule(session, "intrusion")
    d = stored(readers)
    readers[source].down = True
    r = client.post(URL, json=payload(d), headers=c3)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "dependency_unavailable"


def test_c3_reader_not_configured_is_503(client, c3, readers):
    client.app.dependency_overrides[get_detection_reader] = lambda: None
    r = client.post(URL, json=payload(stored(readers)), headers=c3)
    assert (r.status_code, r.json()["error"]["details"]) == (503, {"source": "c3"})


def test_only_the_evaluate_scope_may_call(client, auth_header, readers):
    body = payload(stored(readers))
    for headers in (
        auth_header(user_id=STAFF_USER, role="cloud_staff", tenant_id=TENANT_A),
        auth_header(
            user_id=OWNER_USER, role="house_owner", tenant_id=TENANT_A, house_ids=[HOUSE_A1]
        ),
        auth_header(service_scopes=["alerts:read"]),
    ):
        r = client.post(URL, json=body, headers=headers)
        assert (r.status_code, r.json()["error"]["code"]) == (403, "forbidden")
    assert client.post(URL, json=body).status_code == 401


# --- the race: two evaluates of one detection at the same time ------------------------------


@pytest.fixture
def committed_rule(pg_engine):
    """A committed tenant default for intrusion; everything it produced is removed after."""
    with Session(pg_engine) as s:
        t = alert_type(s, "intrusion")
        rule = AlertRule(
            tenant_id=TENANT_A,
            alert_type_id=t.alert_type_id,
            trigger_labels=["glass_break"],
            min_confidence=0.55,
            created_by=STAFF_USER,
        )
        s.add(rule)
        s.commit()
        rule_id = rule.rule_id
    try:
        yield rule_id
    finally:
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM c2.alert_status_history WHERE alert_id IN "
                    "(SELECT alert_id FROM c2.alerts WHERE rule_id = :r)"
                ),
                {"r": rule_id},
            )
            conn.execute(text("DELETE FROM c2.alerts WHERE rule_id = :r"), {"r": rule_id})
            conn.execute(text("DELETE FROM c2.alert_rules WHERE rule_id = :r"), {"r": rule_id})


def test_concurrent_evaluate_of_one_detection_creates_one_alert(
    pg_engine, committed_rule, readers, monkeypatch
):
    d = stored(readers)
    req = EvaluateRequest.model_validate(payload(d))
    barrier = threading.Barrier(2, timeout=10)
    original = AlertRepository.add

    def add_after_both_decided(self, alert):
        barrier.wait()  # both found no existing alert and decided "alert" before inserting
        return original(self, alert)

    monkeypatch.setattr(AlertRepository, "add", add_after_both_decided)
    results: list[tuple[bool, dict]] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            with Session(pg_engine) as s:
                engine = RuleEngine(
                    alerts=AlertRepository(s),
                    rules=RuleRepository(s),
                    detections=readers["detections"],
                    houses=readers["houses"],
                    settings=readers["settings"],
                    clock=lambda: NOON_LA,
                )
                outcome = evaluate_detection(engine, AlertLifecycleService(s), req)
                results.append((outcome.created, outcome.result.model_dump(exclude_none=True)))
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert errors == []
    created = [r for c, r in results if c]
    duplicates = [r for c, r in results if not c]
    assert len(created) == 1 and len(duplicates) == 1
    assert duplicates[0] == {
        "decision": "alert",
        "alert_id": created[0]["alert_id"],
        "duplicate": True,
    }
    with Session(pg_engine) as s:
        alerts = s.scalars(select(Alert).where(Alert.detection_id == d.detection_id)).all()
        assert len(alerts) == 1
        assert len(HistoryRepository(s).list_for_alert(alerts[0].alert_id)) == 1
