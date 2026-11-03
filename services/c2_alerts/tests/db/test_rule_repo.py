"""RuleRepository: duplicates, versioned update, soft delete, scoping, evaluation order."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.models.orm import AlertRule
from app.repositories.errors import DuplicateRuleError
from app.repositories.rule_repo import RuleRepository
from app.repositories.scope import Scope
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.factories import (
    HOUSE_A1,
    HOUSE_A2,
    ROOM_A1_BATH,
    ROOM_A1_KITCHEN,
    STAFF_USER,
    TENANT_A,
    TENANT_B,
    alert_type,
    make_alert,
    make_rule,
)

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _new_rule(session, code, **kw) -> AlertRule:
    t = alert_type(session, code)
    return AlertRule(
        tenant_id=kw.pop("tenant_id", TENANT_A),
        alert_type_id=t.alert_type_id,
        trigger_labels=[t.trigger_label],
        min_confidence=t.default_min_confidence,
        created_by=STAFF_USER,
        **kw,
    )


# --- add / duplicates -----------------------------------------------------------------------


def test_add_duplicate_enabled_rule_raises_and_session_stays_usable(session):
    repo = RuleRepository(session)
    repo.add(_new_rule(session, "fall", house_id=HOUSE_A1, room_id=ROOM_A1_BATH))
    with pytest.raises(DuplicateRuleError):
        repo.add(_new_rule(session, "fall", house_id=HOUSE_A1, room_id=ROOM_A1_BATH))
    # The savepoint kept the outer transaction alive.
    assert session.execute(text("SELECT 1")).scalar() == 1
    assert len(repo.enabled_for(TENANT_A, HOUSE_A1, ROOM_A1_BATH)) == 1


def test_duplicate_tenant_default_detected_with_null_house_and_room(session):
    repo = RuleRepository(session)
    repo.add(_new_rule(session, "smoke"))
    with pytest.raises(DuplicateRuleError):
        repo.add(_new_rule(session, "smoke"))


@pytest.mark.parametrize(
    "other",
    [
        {"house_id": HOUSE_A2},  # different house
        {"room_id": ROOM_A1_KITCHEN},  # different room
        {"is_enabled": False},  # disabled rules don't count
        {"tenant_id": TENANT_B},  # different tenant
    ],
)
def test_not_a_duplicate(session, other):
    repo = RuleRepository(session)
    repo.add(_new_rule(session, "fall", house_id=HOUSE_A1, room_id=ROOM_A1_BATH))
    kw = {"house_id": HOUSE_A1, "room_id": ROOM_A1_BATH, **other}
    repo.add(_new_rule(session, "fall", **kw))


def test_deleted_rule_does_not_block_new_one(session):
    repo = RuleRepository(session)
    first = repo.add(_new_rule(session, "fall", house_id=HOUSE_A1))
    assert repo.soft_delete(first.rule_id, Scope(tenant_id=TENANT_A))
    repo.add(_new_rule(session, "fall", house_id=HOUSE_A1))


# --- get / update / delete ------------------------------------------------------------------


def test_get_is_tenant_scoped_and_hides_deleted(session):
    repo = RuleRepository(session)
    rule = make_rule(session, "fall", house_id=HOUSE_A1)
    assert repo.get(rule.rule_id, Scope(tenant_id=TENANT_A)) is not None
    assert repo.get(rule.rule_id, Scope.everything()) is not None
    assert repo.get(rule.rule_id, Scope(tenant_id=TENANT_B)) is None
    repo.soft_delete(rule.rule_id, Scope.everything())
    assert repo.get(rule.rule_id, Scope.everything()) is None


def test_update_bumps_version_and_updated_at(session):
    repo = RuleRepository(session)
    rule = make_rule(session, "fall", house_id=HOUSE_A1)
    session.execute(
        text("UPDATE c2.alert_rules SET updated_at = :t WHERE rule_id = :r"),
        {"t": T0, "r": rule.rule_id},
    )
    updated = repo.update(
        rule.rule_id, 1, Scope(tenant_id=TENANT_A), min_confidence=0.7, severity="critical"
    )
    assert updated is not None
    assert updated.version == 2
    assert updated.min_confidence == 0.7
    assert updated.severity == "critical"
    assert updated.updated_at > T0


def test_update_with_stale_version_or_other_tenant_matches_nothing(session):
    repo = RuleRepository(session)
    rule = make_rule(session, "fall", house_id=HOUSE_A1)
    assert repo.update(rule.rule_id, 2, Scope.everything(), min_confidence=0.7) is None
    assert repo.update(rule.rule_id, 1, Scope(tenant_id=TENANT_B), min_confidence=0.7) is None
    session.refresh(rule)
    assert (rule.version, rule.min_confidence) == (1, 0.65)


def test_update_rejects_non_editable_fields(session):
    rule = make_rule(session, "fall", house_id=HOUSE_A1)
    with pytest.raises(ValueError, match="tenant_id"):
        RuleRepository(session).update(rule.rule_id, 1, Scope.everything(), tenant_id=TENANT_B)


def test_reenabling_into_a_duplicate_raises(session):
    repo = RuleRepository(session)
    make_rule(session, "fall", house_id=HOUSE_A1)
    disabled = make_rule(session, "fall", house_id=HOUSE_A1, is_enabled=False)
    with pytest.raises(DuplicateRuleError):
        repo.update(disabled.rule_id, 1, Scope.everything(), is_enabled=True)
    assert session.execute(text("SELECT 1")).scalar() == 1


def test_soft_delete_scoped_and_idempotent(session):
    repo = RuleRepository(session)
    rule = make_rule(session, "fall", house_id=HOUSE_A1)
    assert repo.soft_delete(rule.rule_id, Scope(tenant_id=TENANT_B)) is False
    assert repo.soft_delete(rule.rule_id, Scope(tenant_id=TENANT_A)) is True
    assert repo.soft_delete(rule.rule_id, Scope(tenant_id=TENANT_A)) is False


# --- list -----------------------------------------------------------------------------------


def test_list_filters_scope_and_paging(session):
    repo = RuleRepository(session)
    make_rule(session, "fall", house_id=HOUSE_A1, created_at=T0)
    make_rule(session, "smoke", created_at=T0 + timedelta(minutes=1))
    make_rule(
        session, "pet", house_id=HOUSE_A1, is_enabled=False, created_at=T0 + timedelta(minutes=2)
    )
    make_rule(session, "fall", tenant_id=TENANT_B, house_id=HOUSE_A1)
    deleted = make_rule(session, "presence")
    repo.soft_delete(deleted.rule_id, Scope.everything())

    rows, total = repo.list(Scope(tenant_id=TENANT_A))
    assert total == 3
    assert [r.alert_type.code for r, _ in rows] == ["pet", "smoke", "fall"]  # newest first

    assert repo.list(Scope(tenant_id=TENANT_A), house_id=HOUSE_A1)[1] == 2
    assert repo.list(Scope(tenant_id=TENANT_A), alert_type_code="fall")[1] == 1
    assert repo.list(Scope(tenant_id=TENANT_A), is_enabled=False)[1] == 1
    assert repo.list(Scope.everything())[1] == 4

    page, total = repo.list(Scope(tenant_id=TENANT_A), offset=1, limit=1)
    assert total == 3
    assert [r.alert_type.code for r, _ in page] == ["smoke"]


def test_list_counts_false_positives_in_last_30_days(session):
    repo = RuleRepository(session)
    rule = make_rule(session, "intrusion", house_id=HOUSE_A1)
    now = datetime.now(UTC)
    make_alert(session, rule, status="false_positive", triggered_at=now - timedelta(days=1))
    make_alert(session, rule, status="false_positive", triggered_at=now - timedelta(days=29))
    make_alert(session, rule, status="false_positive", triggered_at=now - timedelta(days=31))
    make_alert(session, rule, status="resolved", triggered_at=now - timedelta(days=1))
    other = make_rule(session, "fall", house_id=HOUSE_A1)

    counts = {r.rule_id: fp for r, fp in repo.list(Scope(tenant_id=TENANT_A))[0]}
    assert counts == {rule.rule_id: 2, other.rule_id: 0}


# --- enabled_for (evaluation set and order) -------------------------------------------------


def test_enabled_for_orders_by_severity_then_room_then_age(session):
    repo = RuleRepository(session)
    pet = make_rule(session, "pet", house_id=HOUSE_A1, created_at=T0)  # low
    fall_any = make_rule(session, "fall", house_id=HOUSE_A1, created_at=T0)  # high
    fall_bath = make_rule(
        session, "fall", house_id=HOUSE_A1, room_id=ROOM_A1_BATH, created_at=T0 + timedelta(hours=1)
    )  # high, room-specific
    intrusion_old = make_rule(
        session, "intrusion", house_id=HOUSE_A1, room_id=ROOM_A1_KITCHEN, created_at=T0
    )  # high, room, older
    cough_upgraded = make_rule(
        session, "wellness_cough", house_id=HOUSE_A1, severity="critical", created_at=T0
    )  # override beats type default (low)

    # Detection in the Kitchen: the Bathroom fall rule does not apply (kept for room_mismatch).
    ids = [r.rule_id for r in repo.enabled_for(TENANT_A, HOUSE_A1, ROOM_A1_KITCHEN)]
    assert ids == [
        cough_upgraded.rule_id,  # critical
        intrusion_old.rule_id,  # high, room-specific, oldest
        fall_bath.rule_id,  # high, room-specific (other room)
        fall_any.rule_id,  # high, any room
        pet.rule_id,  # low
    ]


def _ids(rules) -> set[str]:
    return {r.rule_id for r in rules}


def test_room_rule_replaces_the_default_only_in_its_room(session):
    """Decision 2026-11-03: most specific applicable rule per type wins (room > house > tenant)."""
    repo = RuleRepository(session)
    smoke_default = make_rule(session, "smoke")
    fall_default = make_rule(session, "fall")
    fall_bath = make_rule(
        session, "fall", house_id=HOUSE_A1, room_id=ROOM_A1_BATH, min_confidence=0.7
    )

    # In the Bathroom the room rule hides the default (so its stricter threshold really applies).
    assert _ids(repo.enabled_for(TENANT_A, HOUSE_A1, ROOM_A1_BATH)) == {
        smoke_default.rule_id,
        fall_bath.rule_id,
    }
    # In the Kitchen the default still applies; the Bathroom rule stays for room_mismatch.
    assert _ids(repo.enabled_for(TENANT_A, HOUSE_A1, ROOM_A1_KITCHEN)) == {
        smoke_default.rule_id,
        fall_default.rule_id,
        fall_bath.rule_id,
    }
    # Unknown room: room rules cannot apply, so the default does.
    assert fall_default.rule_id in _ids(repo.enabled_for(TENANT_A, HOUSE_A1, None))
    # Another house of the tenant only sees the defaults.
    assert _ids(repo.enabled_for(TENANT_A, HOUSE_A2, None)) == {
        smoke_default.rule_id,
        fall_default.rule_id,
    }


def test_whole_house_rule_replaces_default_everywhere_and_room_rule_beats_it(session):
    repo = RuleRepository(session)
    fall_default = make_rule(session, "fall")
    fall_house = make_rule(session, "fall", house_id=HOUSE_A1)
    fall_bath = make_rule(session, "fall", house_id=HOUSE_A1, room_id=ROOM_A1_BATH)

    assert _ids(repo.enabled_for(TENANT_A, HOUSE_A1, ROOM_A1_KITCHEN)) == {
        fall_house.rule_id,
        fall_bath.rule_id,
    }
    assert _ids(repo.enabled_for(TENANT_A, HOUSE_A1, ROOM_A1_BATH)) == {fall_bath.rule_id}
    assert fall_default.rule_id not in _ids(repo.enabled_for(TENANT_A, HOUSE_A1, None))


def test_enabled_for_ignores_disabled_deleted_and_other_tenants(session):
    repo = RuleRepository(session)
    make_rule(session, "fall", house_id=HOUSE_A1, is_enabled=False)
    gone = make_rule(session, "smoke", house_id=HOUSE_A1)
    repo.soft_delete(gone.rule_id, Scope.everything())
    make_rule(session, "pet", tenant_id=TENANT_B)
    default_fall = make_rule(session, "fall")

    # Decision 2026-11-03: a disabled house rule does not hide the tenant default.
    assert [r.rule_id for r in repo.enabled_for(TENANT_A, HOUSE_A1, None)] == [default_fall.rule_id]
    assert repo.enabled_for(TENANT_B, HOUSE_A1, None)[0].alert_type.code == "pet"


# --- defaults -------------------------------------------------------------------------------


def test_types_missing_default(session):
    repo = RuleRepository(session)
    assert len(repo.types_missing_default(TENANT_A)) == 7
    make_rule(session, "smoke")
    make_rule(session, "fall", house_id=HOUSE_A1)  # house rule is not a default
    make_rule(session, "pet", is_enabled=False)  # disabled default does not count
    missing = {t.code for t in repo.types_missing_default(TENANT_A)}
    assert missing == {"distress", "intrusion", "fall", "wellness_cough", "presence", "pet"}
    assert len(repo.types_missing_default(TENANT_B)) == 7


def test_other_integrity_errors_are_not_reported_as_duplicates(session):
    rule = _new_rule(session, "fall", house_id=HOUSE_A1)
    rule.alert_type_id = 999  # foreign key violation, not ux_rules_dup
    with pytest.raises(IntegrityError, match="alert_type_id"):
        RuleRepository(session).add(rule)
