"""``POST /alerts/evaluate``: decide, raise the alert exactly once, answer per contract 4.3.

Notifications (in-app record + contact emails) are added after the commit in C2-09.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.evaluate import EvaluateRequest, EvaluateResult
from app.services.lifecycle import AlertLifecycleService
from app.services.rule_engine import RuleEngine


@dataclass(frozen=True)
class EvaluateOutcome:
    result: EvaluateResult
    created: bool  # True only when this call raised a new alert (HTTP 201)


def evaluate_detection(
    engine: RuleEngine, lifecycle: AlertLifecycleService, req: EvaluateRequest
) -> EvaluateOutcome:
    decision, detection = engine.evaluate(req)

    if decision.duplicate:
        return EvaluateOutcome(
            EvaluateResult(decision="alert", alert_id=decision.alert_id, duplicate=True), False
        )
    if not decision.is_alert:
        return EvaluateOutcome(EvaluateResult(decision="no_alert", reason=decision.reason), False)

    # The rule's tenant is the house's tenant (enabled_for only returns that tenant's rules).
    raised = lifecycle.raise_alert(decision, detection, decision.rule.tenant_id)
    if raised.duplicate:  # lost a race with a concurrent evaluate of the same detection
        return EvaluateOutcome(
            EvaluateResult(decision="alert", alert_id=raised.alert.alert_id, duplicate=True), False
        )
    return EvaluateOutcome(
        EvaluateResult(
            decision="alert",
            alert_id=raised.alert.alert_id,
            severity=raised.alert.severity,
            duplicate=False,
        ),
        True,
    )
