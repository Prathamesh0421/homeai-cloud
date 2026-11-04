"""Test data builders for C2 rows (fixed-looking UUIDs keep assertions readable)."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.gateways.types import House, Room
from app.models.orm import Alert, AlertRule, AlertType
from sqlalchemy import select
from sqlalchemy.orm import Session

TENANT_A = "11111111-0000-0000-0000-000000000001"
TENANT_B = "11111111-0000-0000-0000-000000000002"
HOUSE_A1 = "22222222-0000-0000-0000-0000000000a1"
HOUSE_A2 = "22222222-0000-0000-0000-0000000000a2"
HOUSE_B1 = "22222222-0000-0000-0000-0000000000b1"
# Same IDs as the seed (scripts/seed_ids.py): Maple Bathroom and Kitchen.
ROOM_A1_BATH = "33333333-0000-0000-0000-00000000a104"
ROOM_A1_KITCHEN = "33333333-0000-0000-0000-00000000a101"
STAFF_USER = "44444444-0000-0000-0000-000000000001"
OWNER_USER = "44444444-0000-0000-0000-000000000002"

MAPLE = House(HOUSE_A1, TENANT_A, "Maple St", "America/Los_Angeles")
OAK = House(HOUSE_A2, TENANT_A, "Oak Ave", "America/Los_Angeles")
PINE = House(HOUSE_B1, TENANT_B, "Pine Rd", "America/New_York")
BATH = Room(ROOM_A1_BATH, HOUSE_A1, "Bathroom")
KITCHEN = Room(ROOM_A1_KITCHEN, HOUSE_A1, "Kitchen")


def uid() -> str:
    return str(uuid.uuid4())


def alert_type(session: Session, code: str) -> AlertType:
    return session.scalars(select(AlertType).where(AlertType.code == code)).one()


def make_rule(
    session: Session,
    code: str,
    *,
    tenant_id: str = TENANT_A,
    house_id: str | None = None,
    room_id: str | None = None,
    severity: str | None = None,
    min_confidence: float | None = None,
    trigger_labels: list[str] | None = None,
    is_enabled: bool = True,
    created_at: datetime | None = None,
) -> AlertRule:
    t = alert_type(session, code)
    rule = AlertRule(
        tenant_id=tenant_id,
        house_id=house_id,
        room_id=room_id,
        alert_type_id=t.alert_type_id,
        trigger_labels=trigger_labels or [t.trigger_label],
        min_confidence=min_confidence if min_confidence is not None else t.default_min_confidence,
        severity=severity,
        is_enabled=is_enabled,
        created_by=STAFF_USER,
    )
    if created_at is not None:
        rule.created_at = created_at
    session.add(rule)
    session.flush()
    return rule


def make_alert(
    session: Session,
    rule: AlertRule,
    *,
    house_id: str | None = None,
    status: str = "open",
    severity: str | None = None,
    triggered_at: datetime | None = None,
    detection_id: str | None = None,
    room_id: str | None = None,
    threshold: float | None = None,
) -> Alert:
    alert = build_alert(rule, house_id=house_id, severity=severity, detection_id=detection_id)
    alert.status = status
    alert.threshold = threshold
    if room_id is not None:
        alert.room_id = room_id
    if triggered_at is not None:
        alert.triggered_at = triggered_at
    session.add(alert)
    session.flush()
    return alert


def build_alert(
    rule: AlertRule,
    *,
    house_id: str | None = None,
    severity: str | None = None,
    detection_id: str | None = None,
) -> Alert:
    """An unsaved Alert for ``rule`` (for repository ``add`` tests)."""
    return Alert(
        tenant_id=rule.tenant_id,
        house_id=house_id or rule.house_id or HOUSE_A1,
        room_id=rule.room_id,
        alert_type_id=rule.alert_type_id,
        rule_id=rule.rule_id,
        detection_id=detection_id or uid(),
        media_id=uid(),
        top_label=rule.trigger_labels[0],
        top_confidence=0.78,
        severity=severity or rule.severity or "high",
    )
