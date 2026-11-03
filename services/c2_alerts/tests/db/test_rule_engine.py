"""RuleEngine.evaluate: rules from Postgres, C1/C4/C3 through the fakes, fixed clock."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time

import pytest
from app.constants import SERVICE_CODES
from app.gateways.types import DependencyUnavailableError, Detection, HouseSettings
from app.repositories.alert_repo import AlertRepository
from app.repositories.rule_repo import RuleRepository
from app.schemas.evaluate import EvaluateRequest
from app.services.rule_engine import RuleEngine
from homeai_common.errors import ApiError

from tests.factories import (
    BATH,
    HOUSE_A1,
    HOUSE_A2,
    KITCHEN,
    MAPLE,
    OAK,
    ROOM_A1_BATH,
    ROOM_A1_KITCHEN,
    TENANT_A,
    TENANT_B,
    make_alert,
    make_rule,
    uid,
)
from tests.fakes import FakeDetectionReader, FakeHouseReader, FakeSettingsReader

NOON_LA = datetime(2026, 10, 25, 19, 0, tzinfo=UTC)
NIGHT_LA = datetime(2026, 10, 25, 6, 10, tzinfo=UTC)  # 23:10 in Maple St's timezone

MAPLE_QUIET = HouseSettings(
    house_id=HOUSE_A1,
    tenant_id=TENANT_A,
    enabled_services=frozenset(SERVICE_CODES),
    quiet_start=time(22, 0),
    quiet_end=time(7, 0),
    sensitivity="medium",
)


@pytest.fixture
def world(session):
    detections = FakeDetectionReader()
    houses = FakeHouseReader([MAPLE, OAK], [BATH, KITCHEN])
    settings = FakeSettingsReader([MAPLE_QUIET])
    clock = {"now": NOON_LA}
    engine = RuleEngine(
        alerts=AlertRepository(session),
        rules=RuleRepository(session),
        detections=detections,
        houses=houses,
        settings=settings,
        clock=lambda: clock["now"],
    )
    return engine, detections, houses, settings, clock


def stored(detections, label, confidence, *, room_id=ROOM_A1_KITCHEN, house_id=HOUSE_A1):
    d = Detection(
        _id=uid(),
        media_id=uid(),
        tenant_id=TENANT_A,
        house_id=house_id,
        room_id=room_id,
        top_label=label,
        top_confidence=confidence,
        labels=[{"label": label, "confidence": confidence}],
        detected_at=NOON_LA,
    )
    detections.add(d)
    return d


def request_for(d: Detection, **overrides) -> EvaluateRequest:
    body = {
        "detection_id": d.detection_id,
        "media_id": d.media_id,
        "house_id": d.house_id,
        "room_id": d.room_id,
        "top_label": d.top_label,
        "top_confidence": d.top_confidence,
        "labels": [{"label": d.top_label, "confidence": d.top_confidence}],
        "detected_at": d.detected_at.isoformat(),
    }
    body.update(overrides)
    return EvaluateRequest.model_validate(body)


def test_alert_from_tenant_default(world, session):
    engine, detections, *_ = world
    rule = make_rule(session, "intrusion")
    d = stored(detections, "glass_break", 0.78)
    decision, detection = engine.evaluate(request_for(d))
    assert decision.is_alert
    assert (decision.rule.rule_id, decision.severity, decision.threshold) == (
        rule.rule_id,
        "high",
        0.55,
    )
    assert detection == d


def test_decision_uses_the_stored_detection_not_the_request(world, session):
    engine, detections, *_ = world
    make_rule(session, "intrusion")
    d = stored(detections, "glass_break", 0.30)
    decision, _ = engine.evaluate(request_for(d, top_confidence=0.99))
    assert decision.reason == "below_threshold"


def test_existing_alert_is_a_duplicate_without_reading_anything(world, session):
    engine, detections, houses, settings, _ = world
    rule = make_rule(session, "intrusion", house_id=HOUSE_A1)
    d = stored(detections, "glass_break", 0.78)
    alert = make_alert(session, rule, detection_id=d.detection_id, severity="high")
    detections.down = houses.down = settings.down = True  # proves step 1 runs first

    decision, detection = engine.evaluate(request_for(d))
    assert (decision.decision, decision.duplicate, decision.alert_id) == (
        "alert",
        True,
        alert.alert_id,
    )
    assert decision.severity == "high"
    assert detection is None


@pytest.mark.parametrize(
    ("setup", "field"),
    [
        (lambda det: (det, {"detection_id": uid()}), "detection_id"),
        (lambda det: (det, {"house_id": HOUSE_A2}), "house_id"),
    ],
)
def test_unknown_detection_or_wrong_house_is_422(world, setup, field):
    engine, detections, *_ = world
    d, overrides = setup(stored(detections, "glass_break", 0.78))
    with pytest.raises(ApiError) as exc:
        engine.evaluate(request_for(d, **overrides))
    assert exc.value.status_code == 422
    assert exc.value.details[0]["field"] == field


def test_unknown_house_is_422(world):
    engine, detections, *_ = world
    d = stored(detections, "glass_break", 0.78, house_id=uid())
    with pytest.raises(ApiError) as exc:
        engine.evaluate(request_for(d))
    assert exc.value.details == [{"field": "house_id", "issue": "unknown house"}]


@pytest.mark.parametrize("source", ["detections", "houses", "settings"])
def test_a_source_down_is_dependency_unavailable(world, session, source):
    engine, detections, houses, settings, _ = world
    make_rule(session, "intrusion")
    d = stored(detections, "glass_break", 0.78)
    {"detections": detections, "houses": houses, "settings": settings}[source].down = True
    with pytest.raises(DependencyUnavailableError):
        engine.evaluate(request_for(d))


def test_other_tenants_rules_do_not_apply(world, session):
    engine, detections, *_ = world
    make_rule(session, "intrusion", tenant_id=TENANT_B)
    d = stored(detections, "glass_break", 0.99)
    assert engine.evaluate(request_for(d))[0].reason == "no_rule_match"


def test_room_rule_applies_only_in_its_room(world, session):
    # Decision 2026-11-03: Bathroom rule (0.70) replaces the fall default (0.65) only there.
    engine, detections, *_ = world
    make_rule(session, "fall")
    bath = make_rule(session, "fall", house_id=HOUSE_A1, room_id=ROOM_A1_BATH, min_confidence=0.70)

    in_bath = engine.evaluate(
        request_for(stored(detections, "fall_indicator", 0.67, room_id=ROOM_A1_BATH))
    )
    assert (in_bath[0].reason, in_bath[0].threshold) == ("below_threshold", 0.70)

    in_kitchen = engine.evaluate(request_for(stored(detections, "fall_indicator", 0.67)))
    assert in_kitchen[0].is_alert
    assert in_kitchen[0].rule.house_id is None  # the tenant default fired

    strong_bath = engine.evaluate(
        request_for(stored(detections, "fall_indicator", 0.75, room_id=ROOM_A1_BATH))
    )
    assert strong_bath[0].rule.rule_id == bath.rule_id


def test_night_time_scenario_quiet_hours_and_severity(world, session):
    # I-3 / demo 10.1 step 5: cough (low) is held at night, glass break (high) goes through.
    engine, detections, _, _, clock = world
    make_rule(session, "wellness_cough")
    make_rule(session, "intrusion")
    clock["now"] = NIGHT_LA

    cough, _ = engine.evaluate(request_for(stored(detections, "cough", 0.80)))
    assert (cough.decision, cough.reason, cough.severity) == ("no_alert", "quiet_hours", "low")
    glass, _ = engine.evaluate(request_for(stored(detections, "glass_break", 0.78)))
    assert (glass.decision, glass.severity) == ("alert", "high")

    clock["now"] = NOON_LA
    assert engine.evaluate(request_for(stored(detections, "cough", 0.80)))[0].is_alert


def test_house_without_settings_row_uses_defaults(world, session):
    # Oak Ave has no settings row in the fake: all services on, no quiet hours, medium.
    engine, detections, _, _, clock = world
    make_rule(session, "wellness_cough")
    clock["now"] = NIGHT_LA
    d = stored(detections, "cough", 0.60, house_id=HOUSE_A2, room_id=None)
    assert engine.evaluate(request_for(d))[0].is_alert


def test_every_decision_is_logged(world, session, caplog):
    engine, detections, *_ = world
    rule = make_rule(session, "intrusion")
    d = stored(detections, "glass_break", 0.78)
    with caplog.at_level(logging.INFO, logger="app.services.rule_engine"):
        engine.evaluate(request_for(d))
    (record,) = [r for r in caplog.records if r.getMessage() == "evaluate decision"]
    assert (record.detection_id, record.decision, record.rule_id, record.threshold) == (
        d.detection_id,
        "alert",
        rule.rule_id,
        0.55,
    )
