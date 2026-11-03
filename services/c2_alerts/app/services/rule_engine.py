"""RuleEngine: turn a detection into an alert decision (C2 plan §4.1).

``decide()`` is pure (rules, detection, settings, clock in -> Decision out) so every row of
the D2 rule-match table is unit-tested. ``RuleEngine.evaluate()`` gathers those inputs from
C2's tables and the read-only gateways. Raising the alert and notifying contacts happen in
the lifecycle and notification services (C2-06, C2-09).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from homeai_common.errors import ApiError

from app.gateways.types import (
    Detection,
    DetectionReader,
    HouseReader,
    HouseSettings,
    SettingsReader,
)
from app.models.orm import AlertRule
from app.repositories.alert_repo import AlertRepository
from app.repositories.rule_repo import RuleRepository
from app.schemas.evaluate import EvaluateRequest
from app.services.quiet_hours import in_quiet_hours, utc_now

logger = logging.getLogger(__name__)

SENSITIVITY_SHIFT = {"low": 0.10, "medium": 0.0, "high": -0.10}
THRESHOLD_MIN, THRESHOLD_MAX = 0.05, 0.95
QUIET_HOURS_HOLD = frozenset({"medium", "low"})  # critical and high always go through

# Lowest to highest: the most "explanatory" miss is reported (contracts §3).
REASON_PRECEDENCE: tuple[str, ...] = (
    "no_rule_match",
    "service_disabled",
    "below_threshold",
    "room_mismatch",
)
_RANK = {reason: i for i, reason in enumerate(REASON_PRECEDENCE)}


def effective_threshold(min_confidence: float, sensitivity: str) -> float:
    """Rule threshold shifted by house sensitivity, clamped to 0.05-0.95, rounded to 2 dp.

    Rounding keeps float drift (0.55 + 0.10 = 0.6500000000000001) from failing a 0.65 match.
    """
    shifted = min_confidence + SENSITIVITY_SHIFT.get(sensitivity, 0.0)
    return round(min(THRESHOLD_MAX, max(THRESHOLD_MIN, shifted)), 2)


@dataclass(frozen=True)
class Decision:
    """Outcome for one detection. ``rule``/``severity``/``threshold`` are set for alerts."""

    decision: str  # "alert" | "no_alert"
    reason: str | None = None
    rule: AlertRule | None = None
    severity: str | None = None
    threshold: float | None = None
    alert_id: str | None = None  # set when an alert already exists (duplicate)
    duplicate: bool = False

    @property
    def is_alert(self) -> bool:
        return self.decision == "alert"

    @classmethod
    def no_alert(cls, reason: str, threshold: float | None = None) -> Decision:
        return cls("no_alert", reason=reason, threshold=threshold)


def decide(
    detection: Detection,
    rules: Sequence[AlertRule],
    settings: HouseSettings,
    house_timezone: str,
    now: datetime,
) -> Decision:
    """Steps 5-7 of the plan. ``rules`` must already be in evaluation order (``enabled_for``)."""
    best_miss = "no_rule_match"
    miss_threshold: float | None = None

    def miss(reason: str, threshold: float | None = None) -> None:
        nonlocal best_miss, miss_threshold
        if _RANK[reason] > _RANK[best_miss]:
            best_miss, miss_threshold = reason, threshold

    for rule in rules:
        alert_type = rule.alert_type
        # Label first: a rule for another label says nothing about this detection, so a
        # disabled service only explains a miss when its rule would have matched the label.
        if detection.top_label not in rule.trigger_labels:
            continue
        if alert_type.service_code not in settings.enabled_services:
            miss("service_disabled")
            continue
        threshold = effective_threshold(rule.min_confidence, settings.sensitivity)
        if detection.top_confidence < threshold:
            miss("below_threshold", threshold)
            continue
        if rule.room_id is not None and rule.room_id != detection.room_id:
            miss("room_mismatch", threshold)
            continue
        severity = rule.severity or alert_type.default_severity
        if severity in QUIET_HOURS_HOLD and in_quiet_hours(
            now, house_timezone, settings.quiet_start, settings.quiet_end
        ):
            return Decision(
                "no_alert", reason="quiet_hours", rule=rule, severity=severity, threshold=threshold
            )
        return Decision("alert", rule=rule, severity=severity, threshold=threshold)
    return Decision.no_alert(best_miss, miss_threshold)


def _invalid(field: str, issue: str) -> ApiError:
    return ApiError(
        422, "validation_error", "request validation failed", [{"field": field, "issue": issue}]
    )


@dataclass
class RuleEngine:
    alerts: AlertRepository
    rules: RuleRepository
    detections: DetectionReader
    houses: HouseReader
    settings: SettingsReader
    clock: Callable[[], datetime] = utc_now

    def evaluate(self, req: EvaluateRequest) -> tuple[Decision, Detection | None]:
        """Steps 1-7. Returns the decision and the stored detection it was made from.

        Raises 422 if the detection is unknown, belongs to another house, or the house is
        unknown; DependencyUnavailableError (-> 503, C3 retries) if a source is down.
        """
        existing = self.alerts.find_by_detection(req.detection_id)
        if existing is not None:
            self._log(req, Decision("alert", alert_id=existing.alert_id, duplicate=True))
            return Decision(
                "alert", severity=existing.severity, alert_id=existing.alert_id, duplicate=True
            ), None

        detection = self.detections.get(req.detection_id)
        if detection is None:
            raise _invalid("detection_id", "no such detection in ai_detections")
        if detection.house_id != req.house_id:
            raise _invalid("house_id", "does not match the stored detection")

        house = self.houses.house(detection.house_id)
        if house is None:
            raise _invalid("house_id", "unknown house")
        settings = self.settings.settings(house.house_id)
        rules = self.rules.enabled_for(house.tenant_id, house.house_id, detection.room_id)

        decision = decide(detection, rules, settings, house.timezone, self.clock())
        self._log(req, decision)
        return decision, detection

    @staticmethod
    def _log(req: EvaluateRequest, decision: Decision) -> None:
        logger.info(
            "evaluate decision",
            extra={
                "detection_id": req.detection_id,
                "house_id": req.house_id,
                "decision": decision.decision,
                "reason": decision.reason,
                "duplicate": decision.duplicate,
                "rule_id": decision.rule.rule_id if decision.rule else None,
                "threshold": decision.threshold,
            },
        )
