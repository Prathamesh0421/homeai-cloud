"""RuleEngine decision logic (C2 plan §4.1 steps 5-7) with in-memory rules; no I/O."""

from __future__ import annotations

from datetime import UTC, datetime, time

import pytest
from app.constants import SERVICE_CODES
from app.gateways.types import Detection, HouseSettings
from app.models.orm import AlertRule, AlertType
from app.services.rule_engine import (
    REASON_PRECEDENCE,
    decide,
    effective_threshold,
)

HOUSE = "22222222-0000-0000-0000-0000000000a1"
BATH = "33333333-0000-0000-0000-0000000000a1"
KITCHEN = "33333333-0000-0000-0000-0000000000a2"
NOON = datetime(2026, 10, 25, 19, 0, tzinfo=UTC)  # 12:00 in LA
NIGHT = datetime(2026, 10, 25, 6, 10, tzinfo=UTC)  # 23:10 in LA

TYPES = {
    "smoke": ("smoke_alarm", "fire_safety", "critical", 0.50),
    "distress": ("distress_sound", "distress", "critical", 0.60),
    "intrusion": ("glass_break", "intrusion", "high", 0.55),
    "fall": ("fall_indicator", "fall", "high", 0.65),
    "wellness_cough": ("cough", "wellness", "low", 0.55),
    "presence": ("speech", "presence", "low", 0.50),
    "pet": ("dog", "pet", "low", 0.55),
}


def rule(code: str, *, min_confidence=None, room_id=None, severity=None, labels=None) -> AlertRule:
    label, service, default_sev, default_conf = TYPES[code]
    return AlertRule(
        rule_id=f"rule-{code}-{room_id or 'any'}-{min_confidence}",
        tenant_id="t",
        house_id=HOUSE,
        trigger_labels=labels or [label],
        min_confidence=default_conf if min_confidence is None else min_confidence,
        room_id=room_id,
        severity=severity,
        alert_type=AlertType(
            code=code,
            name=code,
            category="x",
            service_code=service,
            trigger_label=label,
            default_severity=default_sev,
            default_min_confidence=default_conf,
        ),
    )


def detection(label: str, confidence: float, room_id: str | None = KITCHEN) -> Detection:
    return Detection(
        _id="d1",
        media_id="m1",
        tenant_id="t",
        house_id=HOUSE,
        room_id=room_id,
        top_label=label,
        top_confidence=confidence,
        labels=[{"label": label, "confidence": confidence}] if label != "none" else [],
        detected_at=NOON,
    )


def settings(
    *, disabled=(), sensitivity="medium", quiet=(time(22, 0), time(7, 0))
) -> HouseSettings:
    return HouseSettings(
        house_id=HOUSE,
        tenant_id="t",
        enabled_services=frozenset(set(SERVICE_CODES) - set(disabled)),
        quiet_start=quiet[0] if quiet else None,
        quiet_end=quiet[1] if quiet else None,
        sensitivity=sensitivity,
    )


def run(rules, d, s=None, now=NOON):
    return decide(d, rules, s or settings(), "America/Los_Angeles", now)


# --- thresholds -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("min_conf", "sensitivity", "expected"),
    [
        (0.55, "medium", 0.55),
        (0.55, "low", 0.65),  # less sensitive: higher bar
        (0.55, "high", 0.45),  # more sensitive: lower bar
        (0.90, "low", 0.95),  # clamped high
        (0.10, "high", 0.05),  # clamped low
        (0.02, "medium", 0.05),
        (1.00, "medium", 0.95),
    ],
)
def test_effective_threshold(min_conf, sensitivity, expected):
    assert effective_threshold(min_conf, sensitivity) == expected


def test_threshold_has_no_float_drift():
    # 0.55 + 0.10 is 0.6500000000000001 in floats; a 0.65 detection must still pass.
    d = run([rule("intrusion")], detection("glass_break", 0.65), settings(sensitivity="low"))
    assert d.is_alert


def test_unknown_sensitivity_counts_as_medium():
    assert effective_threshold(0.55, "extreme") == 0.55


# --- matches --------------------------------------------------------------------------------


def test_alert_uses_type_default_severity_and_reports_threshold():
    d = run([rule("intrusion")], detection("glass_break", 0.78))
    assert d.is_alert
    assert (d.rule.alert_type.code, d.severity, d.threshold, d.reason) == (
        "intrusion",
        "high",
        0.55,
        None,
    )


def test_rule_severity_override_wins():
    d = run([rule("presence", severity="medium")], detection("speech", 0.9))
    assert d.severity == "medium"


def test_threshold_is_inclusive():
    assert run([rule("intrusion")], detection("glass_break", 0.55)).is_alert
    assert not run([rule("intrusion")], detection("glass_break", 0.549)).is_alert


def test_sensitivity_high_lets_a_borderline_cough_alert():
    # I-3: with sensitivity high a 0.50 cough (default 0.55) alerts outside quiet hours.
    cough = detection("cough", 0.50)
    assert run([rule("wellness_cough")], cough).reason == "below_threshold"
    assert run([rule("wellness_cough")], cough, settings(sensitivity="high")).is_alert


def test_first_matching_rule_in_order_wins():
    strict = rule("fall", min_confidence=0.70, room_id=KITCHEN)
    loose = rule("fall", min_confidence=0.60)
    d = run([strict, loose], detection("fall_indicator", 0.80))
    assert d.rule is strict


def test_rule_with_several_labels():
    r = rule("distress", labels=["distress_sound", "speech"])
    assert run([r], detection("speech", 0.9)).is_alert


# --- reasons and precedence -----------------------------------------------------------------


def test_no_rules_or_no_label():
    assert run([], detection("glass_break", 0.9)).reason == "no_rule_match"
    assert run([rule("intrusion")], detection("none", 0.0)).reason == "no_rule_match"
    assert run([rule("intrusion")], detection("dog", 0.9)).reason == "no_rule_match"


def test_service_disabled_only_counts_for_rules_matching_the_label():
    s = settings(disabled=["wellness"])
    assert run([rule("wellness_cough")], detection("cough", 0.9), s).reason == "service_disabled"
    # Wellness being off says nothing about a glass break with no intrusion rule.
    assert run([rule("wellness_cough")], detection("glass_break", 0.9), s).reason == "no_rule_match"


def test_disabled_service_never_alerts_even_above_threshold():
    s = settings(disabled=["intrusion"])
    assert not run([rule("intrusion")], detection("glass_break", 0.99), s).is_alert


def test_room_mismatch():
    d = run([rule("fall", room_id=BATH)], detection("fall_indicator", 0.9, room_id=KITCHEN))
    assert d.reason == "room_mismatch"
    assert run(
        [rule("fall", room_id=BATH)], detection("fall_indicator", 0.9, room_id=None)
    ).reason == ("room_mismatch")


def test_below_threshold_is_checked_before_room():
    # Below threshold in another room: below_threshold, not room_mismatch, for that rule.
    d = run([rule("fall", room_id=BATH)], detection("fall_indicator", 0.30))
    assert d.reason == "below_threshold"


@pytest.mark.parametrize(
    ("rules", "s", "expected"),
    [
        # room_mismatch > below_threshold
        (
            lambda: [rule("fall", room_id=BATH), rule("fall", min_confidence=0.95)],
            settings(),
            "room_mismatch",
        ),
        # below_threshold > service_disabled
        (
            lambda: [
                rule("fall", min_confidence=0.95),
                rule("pet", labels=["fall_indicator"]),
            ],
            settings(disabled=["pet"]),
            "below_threshold",
        ),
        # room_mismatch > service_disabled
        (
            lambda: [rule("pet", labels=["fall_indicator"]), rule("fall", room_id=BATH)],
            settings(disabled=["pet"]),
            "room_mismatch",
        ),
        # service_disabled > no_rule_match
        (
            lambda: [rule("fall"), rule("intrusion")],
            settings(disabled=["fall"]),
            "service_disabled",
        ),
    ],
)
def test_reason_precedence(rules, s, expected):
    assert run(rules(), detection("fall_indicator", 0.80), s).reason == expected


def test_precedence_constant_matches_contract():
    assert REASON_PRECEDENCE == (
        "no_rule_match",
        "service_disabled",
        "below_threshold",
        "room_mismatch",
    )


# --- quiet hours ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "label", "severity", "expected"),
    [
        ("wellness_cough", "cough", None, "quiet_hours"),  # low: held
        ("presence", "speech", "medium", "quiet_hours"),  # medium: held
        ("intrusion", "glass_break", None, None),  # high: goes through
        ("smoke", "smoke_alarm", None, None),  # critical: goes through
        ("wellness_cough", "cough", "high", None),  # override to high: goes through
    ],
)
def test_quiet_hours_hold_only_medium_and_low(code, label, severity, expected):
    d = run([rule(code, severity=severity)], detection(label, 0.95), now=NIGHT)
    assert d.reason == expected
    assert d.is_alert is (expected is None)


def test_quiet_hours_do_not_apply_outside_the_window_or_without_one():
    cough = detection("cough", 0.95)
    assert run([rule("wellness_cough")], cough, now=NOON).is_alert
    assert run([rule("wellness_cough")], cough, settings(quiet=None), now=NIGHT).is_alert


def test_quiet_hours_only_after_a_real_match():
    # A below-threshold cough at night is below_threshold, not quiet_hours.
    d = run([rule("wellness_cough")], detection("cough", 0.10), now=NIGHT)
    assert d.reason == "below_threshold"
