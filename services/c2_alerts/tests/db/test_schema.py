"""Migrations 0001/0002: seeded alert types match contracts §3; DB constraints hold."""

from __future__ import annotations

import pytest
from app.repositories.alert_type_repo import AlertTypeRepository
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.factories import HOUSE_A1, alert_type, make_alert, make_rule

# docs/02_CONTRACTS.md §3 "Alert type ↔ label ↔ service mapping"
CONTRACT_TYPES = {
    ("smoke", "smoke_alarm", "emergency", "critical", 0.50, "fire_safety"),
    ("distress", "distress_sound", "emergency", "critical", 0.60, "distress"),
    ("intrusion", "glass_break", "security", "high", 0.55, "intrusion"),
    ("fall", "fall_indicator", "safety", "high", 0.65, "fall"),
    ("wellness_cough", "cough", "wellness", "low", 0.55, "wellness"),
    ("presence", "speech", "wellness", "low", 0.50, "presence"),
    ("pet", "dog", "wellness", "low", 0.55, "pet"),
}


def test_seeded_alert_types_match_contract(session):
    types = AlertTypeRepository(session).list_all()
    got = {
        (
            t.code,
            t.trigger_label,
            t.category,
            t.default_severity,
            t.default_min_confidence,
            t.service_code,
        )
        for t in types
    }
    assert got == CONTRACT_TYPES
    assert all(isinstance(t.default_min_confidence, float) for t in types)
    assert all(t.name for t in types)


def test_get_by_code(session):
    repo = AlertTypeRepository(session)
    assert repo.get_by_code("intrusion").trigger_label == "glass_break"
    assert repo.get_by_code("nope") is None


@pytest.mark.parametrize(
    ("sql", "constraint"),
    [
        ("UPDATE c2.alert_rules SET min_confidence = 1.5", "ck_alert_rules_min_confidence"),
        ("UPDATE c2.alert_rules SET trigger_labels = '{}'", "ck_alert_rules_trigger_labels"),
        ("UPDATE c2.alert_rules SET severity = 'urgent'", "ck_alert_rules_severity"),
    ],
)
def test_rule_check_constraints(session, sql, constraint):
    make_rule(session, "fall", house_id=HOUSE_A1)
    with pytest.raises(IntegrityError, match=constraint):
        session.execute(text(sql))


def test_alert_status_check_and_defaults(session):
    alert = make_alert(session, make_rule(session, "intrusion", house_id=HOUSE_A1))
    session.refresh(alert)
    assert alert.status == "open"
    assert alert.triggered_at.tzinfo is not None
    assert isinstance(alert.top_confidence, float)
    with pytest.raises(IntegrityError, match="ck_alerts_status"):
        session.execute(text("UPDATE c2.alerts SET status = 'closed'"))


def test_rule_defaults(session):
    rule = make_rule(session, "pet")
    session.refresh(rule)
    assert rule.version == 1
    assert rule.is_enabled is True
    assert rule.deleted_at is None
    assert alert_type(session, "pet").alert_type_id == rule.alert_type_id
