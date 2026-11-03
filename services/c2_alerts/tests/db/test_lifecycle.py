"""AlertLifecycleService: raising alerts and the concurrent-acknowledge race."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest
from app.gateways.types import Detection
from app.models.orm import Alert, AlertRule, AlertStatusHistory
from app.repositories.alert_repo import AlertRepository
from app.repositories.history_repo import HistoryRepository
from app.services.lifecycle import AlertLifecycleService
from app.services.rule_engine import Decision
from homeai_common.auth import Principal
from homeai_common.errors import ApiError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tests.factories import (
    HOUSE_A1,
    ROOM_A1_KITCHEN,
    STAFF_USER,
    TENANT_A,
    alert_type,
    make_rule,
    uid,
)

STAFF = Principal(kind="user", sub=STAFF_USER, role="cloud_staff", tenant_id=TENANT_A)


def detection(**overrides) -> Detection:
    body = {
        "_id": uid(),
        "media_id": uid(),
        "tenant_id": TENANT_A,
        "house_id": HOUSE_A1,
        "room_id": ROOM_A1_KITCHEN,
        "top_label": "glass_break",
        "top_confidence": 0.78,
        "labels": [{"label": "glass_break", "confidence": 0.78}],
        "detected_at": datetime(2026, 10, 24, 18, 40, 50, tzinfo=UTC),
    }
    body.update(overrides)
    return Detection.model_validate(body)


# --- raise_alert ----------------------------------------------------------------------------


def test_raise_alert_stores_alert_threshold_and_open_history(session):
    rule = make_rule(session, "intrusion")
    d = detection()
    raised = AlertLifecycleService(session).raise_alert(
        Decision("alert", rule=rule, severity="high", threshold=0.45), d, TENANT_A
    )
    a = raised.alert
    assert raised.duplicate is False
    assert (a.status, a.severity, a.threshold, a.rule_id) == ("open", "high", 0.45, rule.rule_id)
    assert (a.detection_id, a.media_id, a.house_id, a.room_id) == (
        d.detection_id,
        d.media_id,
        HOUSE_A1,
        ROOM_A1_KITCHEN,
    )
    assert (a.top_label, a.top_confidence, a.tenant_id) == ("glass_break", 0.78, TENANT_A)
    history = HistoryRepository(session).list_for_alert(a.alert_id)
    assert [(h.from_status, h.to_status, h.actor_id, h.actor_role) for h in history] == [
        (None, "open", "system", "system")
    ]


def test_raising_twice_for_one_detection_returns_the_first(session):
    rule = make_rule(session, "intrusion")
    d = detection()
    service = AlertLifecycleService(session)
    decision = Decision("alert", rule=rule, severity="high", threshold=0.55)
    first = service.raise_alert(decision, d, TENANT_A)
    second = service.raise_alert(decision, d, TENANT_A)
    assert (second.duplicate, second.alert.alert_id) == (True, first.alert.alert_id)
    count = session.scalar(
        select(text("count(*)")).select_from(Alert).where(Alert.detection_id == d.detection_id)
    )
    assert count == 1
    assert len(HistoryRepository(session).list_for_alert(first.alert.alert_id)) == 1


def test_raise_alert_needs_an_alert_decision(session):
    with pytest.raises(ValueError, match="alert decision"):
        AlertLifecycleService(session).raise_alert(
            Decision.no_alert("below_threshold"), detection(), TENANT_A
        )


# --- the real race (committed rows, two connections) ----------------------------------------


@pytest.fixture
def committed_alert(pg_engine):
    """An open alert committed for real; removed afterwards in foreign-key order."""
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
        s.flush()
        alert = Alert(
            tenant_id=TENANT_A,
            house_id=HOUSE_A1,
            alert_type_id=t.alert_type_id,
            rule_id=rule.rule_id,
            detection_id=uid(),
            media_id=uid(),
            top_label="glass_break",
            top_confidence=0.78,
            severity="high",
        )
        s.add(alert)
        s.commit()
        alert_id, rule_id = alert.alert_id, rule.rule_id
    try:
        yield alert_id
    finally:
        with pg_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM c2.alert_status_history WHERE alert_id = :a"), {"a": alert_id}
            )
            conn.execute(text("DELETE FROM c2.notifications WHERE alert_id = :a"), {"a": alert_id})
            conn.execute(text("DELETE FROM c2.alerts WHERE alert_id = :a"), {"a": alert_id})
            conn.execute(text("DELETE FROM c2.alert_rules WHERE rule_id = :r"), {"r": rule_id})


def test_concurrent_acknowledge_one_wins_one_gets_409(pg_engine, committed_alert, monkeypatch):
    barrier = threading.Barrier(2, timeout=10)
    original = AlertRepository.transition

    def transition_after_both_have_read(self, *args, **kwargs):
        barrier.wait()  # both threads have loaded the alert as "open" before either UPDATEs
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AlertRepository, "transition", transition_after_both_have_read)
    outcomes: list[object] = []

    def worker() -> None:
        with Session(pg_engine) as s:
            try:
                alert = AlertLifecycleService(s).transition(
                    committed_alert, "acknowledge", STAFF, "me"
                )
                outcomes.append(alert.status)
            except ApiError as exc:
                outcomes.append((exc.status_code, exc.code, exc.details))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert sorted(outcomes, key=str) == sorted(
        ["acknowledged", (409, "invalid_state", {"from": "acknowledged", "to": "acknowledged"})],
        key=str,
    )
    with Session(pg_engine) as s:
        history = s.scalars(
            select(AlertStatusHistory).where(AlertStatusHistory.alert_id == committed_alert)
        ).all()
        assert [(h.from_status, h.to_status) for h in history] == [("open", "acknowledged")]
