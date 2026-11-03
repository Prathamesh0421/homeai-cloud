"""AlertRepository, HistoryRepository and NotificationRepository against Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.models.orm import Notification
from app.repositories.alert_repo import AlertRepository
from app.repositories.errors import DuplicateDetectionError
from app.repositories.history_repo import HistoryRepository
from app.repositories.notification_repo import NotificationRepository
from app.repositories.scope import Scope
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.factories import (
    HOUSE_A1,
    HOUSE_A2,
    HOUSE_B1,
    TENANT_A,
    TENANT_B,
    build_alert,
    make_alert,
    make_rule,
    uid,
)

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def rule(session):
    return make_rule(session, "intrusion", house_id=HOUSE_A1)


# --- idempotent insert ----------------------------------------------------------------------


def test_add_and_find_by_detection(session, rule):
    repo = AlertRepository(session)
    detection = uid()
    alert = repo.add(build_alert(rule, detection_id=detection))
    assert repo.find_by_detection(detection).alert_id == alert.alert_id
    assert repo.find_by_detection(uid()) is None


def test_second_alert_for_same_detection_raises_and_session_survives(session, rule):
    repo = AlertRepository(session)
    detection = uid()
    first = repo.add(build_alert(rule, detection_id=detection))
    with pytest.raises(DuplicateDetectionError):
        repo.add(build_alert(rule, detection_id=detection))
    # Caller can still re-read the existing alert in the same transaction.
    assert repo.find_by_detection(detection).alert_id == first.alert_id
    assert session.execute(text("SELECT count(*) FROM c2.alerts")).scalar() == 1


# --- scoped reads (tenant isolation) --------------------------------------------------------


def test_get_respects_tenant_and_house_scope(session, rule):
    repo = AlertRepository(session)
    alert = make_alert(session, rule, house_id=HOUSE_A1)
    assert repo.get(alert.alert_id, Scope.everything()) is not None
    assert repo.get(alert.alert_id, Scope(tenant_id=TENANT_A, house_ids=(HOUSE_A1,))) is not None
    assert repo.get(alert.alert_id, Scope(tenant_id=TENANT_A, house_ids=(HOUSE_A2,))) is None
    assert repo.get(alert.alert_id, Scope(tenant_id=TENANT_B)) is None


def test_tenant_b_owner_cannot_list_tenant_a_alerts(session, rule):
    repo = AlertRepository(session)
    make_alert(session, rule, house_id=HOUSE_A1)
    b_rule = make_rule(session, "intrusion", tenant_id=TENANT_B, house_id=HOUSE_B1)
    b_alert = make_alert(session, b_rule, house_id=HOUSE_B1)

    rows, total = repo.list(Scope(tenant_id=TENANT_B, house_ids=(HOUSE_B1,)))
    assert (total, [a.alert_id for a in rows]) == (1, [b_alert.alert_id])
    # Even naming tenant A's house does not leak across tenants.
    assert repo.list(Scope(tenant_id=TENANT_B, house_ids=(HOUSE_A1,)))[1] == 0


def test_owner_with_no_houses_sees_nothing(session, rule):
    make_alert(session, rule)
    assert AlertRepository(session).list(Scope(tenant_id=TENANT_A, house_ids=()))[1] == 0


def test_list_filters_order_and_paging(session, rule):
    repo = AlertRepository(session)
    fall = make_rule(session, "fall", house_id=HOUSE_A2)
    a1 = make_alert(session, rule, status="open", triggered_at=T0)
    a2 = make_alert(session, rule, status="acknowledged", triggered_at=T0 + timedelta(hours=1))
    a3 = make_alert(
        session, fall, status="resolved", severity="high", triggered_at=T0 + timedelta(hours=2)
    )
    a4 = make_alert(
        session, rule, status="open", severity="critical", triggered_at=T0 + timedelta(hours=3)
    )
    scope = Scope(tenant_id=TENANT_A)

    rows, total = repo.list(scope)
    assert total == 4
    assert [a.alert_id for a in rows] == [a4.alert_id, a3.alert_id, a2.alert_id, a1.alert_id]

    assert {a.alert_id for a in repo.list(scope, statuses=["open", "acknowledged"])[0]} == {
        a1.alert_id,
        a2.alert_id,
        a4.alert_id,
    }
    assert [a.alert_id for a in repo.list(scope, severity="critical")[0]] == [a4.alert_id]
    assert [a.alert_id for a in repo.list(scope, alert_type_code="fall")[0]] == [a3.alert_id]
    assert [a.alert_id for a in repo.list(scope, house_id=HOUSE_A2)[0]] == [a3.alert_id]
    window = repo.list(scope, from_=T0 + timedelta(hours=1), to=T0 + timedelta(hours=3))[0]
    assert [a.alert_id for a in window] == [a3.alert_id, a2.alert_id]  # to is exclusive

    page, total = repo.list(scope, offset=2, limit=1)
    assert (total, [a.alert_id for a in page]) == (4, [a2.alert_id])
    assert page[0].alert_type.code == "intrusion"


# --- transitions ----------------------------------------------------------------------------


def test_transition_sets_timestamps(session, rule):
    repo = AlertRepository(session)
    alert = make_alert(session, rule)
    assert repo.transition(alert.alert_id, "open", "acknowledged", at=T0)
    assert (alert.status, alert.acknowledged_at, alert.resolved_at) == ("acknowledged", T0, None)
    later = T0 + timedelta(minutes=5)
    assert repo.transition(alert.alert_id, "acknowledged", "resolved", at=later)
    assert (alert.status, alert.resolved_at, alert.updated_at) == ("resolved", later, later)


def test_false_positive_closes_the_alert(session, rule):
    repo = AlertRepository(session)
    alert = make_alert(session, rule)
    assert repo.transition(alert.alert_id, "open", "false_positive")
    assert alert.status == "false_positive"
    assert alert.resolved_at is not None
    assert alert.acknowledged_at is None


def test_transition_from_wrong_status_changes_nothing(session, rule):
    repo = AlertRepository(session)
    alert = make_alert(session, rule, status="open")
    assert repo.transition(alert.alert_id, "acknowledged", "resolved") is False
    assert repo.transition(uid(), "open", "acknowledged") is False
    session.refresh(alert)
    assert alert.status == "open"


# --- history and notifications --------------------------------------------------------------


def test_history_is_ordered(session, rule):
    alert = make_alert(session, rule)
    repo = HistoryRepository(session)
    repo.add(alert.alert_id, None, "open", "system", "system")
    repo.add(alert.alert_id, "open", "acknowledged", "u1", "house_owner", note="on my way")
    entries = repo.list_for_alert(alert.alert_id)
    assert [(e.from_status, e.to_status) for e in entries] == [
        (None, "open"),
        ("open", "acknowledged"),
    ]
    assert entries[1].note == "on my way"
    assert entries[0].changed_at is not None


def test_notifications_in_app_first_then_by_priority(session, rule):
    alert = make_alert(session, rule)
    repo = NotificationRepository(session)
    for priority in (2, 1):
        repo.add(
            Notification(
                alert_id=alert.alert_id,
                contact_id=uid(),
                channel="email",
                recipient=f"c{priority}@example.com",
                priority=priority,
                status="queued",
            )
        )
    repo.add(Notification(alert_id=alert.alert_id, channel="in_app", status="sent"))
    rows = repo.list_for_alert(alert.alert_id)
    assert [(n.channel, n.priority) for n in rows] == [("in_app", None), ("email", 1), ("email", 2)]
    assert rows[1].attempt_count == 0


def test_other_integrity_errors_are_not_reported_as_duplicates(session, rule):
    alert = build_alert(rule)
    alert.rule_id = uid()  # foreign key violation, not the detection_id unique key
    with pytest.raises(IntegrityError, match="rule_id"):
        AlertRepository(session).add(alert)


def test_stats_rejects_unknown_grouping(session):
    with pytest.raises(ValueError, match="group_by"):
        AlertRepository(session).stats(
            Scope.everything(), "room", from_=T0, to=T0 + timedelta(days=1)
        )
