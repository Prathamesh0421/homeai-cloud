"""``POST /alerts/evaluate``: decide, raise the alert exactly once, notify, answer per 4.3."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.models.orm import Alert
from app.schemas.evaluate import EvaluateRequest, EvaluateResult
from app.services.lifecycle import AlertLifecycleService
from app.services.rule_engine import RuleEngine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvaluateOutcome:
    result: EvaluateResult
    created: bool  # True only when this call raised a new alert (HTTP 201)


def evaluate_detection(
    engine: RuleEngine,
    lifecycle: AlertLifecycleService,
    req: EvaluateRequest,
    notify: Callable[[Alert], object] | None = None,
) -> EvaluateOutcome:
    """``notify`` runs once, after the new alert is committed; its failures never change the
    answer to C3 (the alert exists and shows in-app; email retries are the job's business)."""
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
    if notify is not None:
        try:
            notify(raised.alert)
        except Exception:
            logger.exception("notification failed", extra={"alert_id": raised.alert.alert_id})
    return EvaluateOutcome(
        EvaluateResult(
            decision="alert",
            alert_id=raised.alert.alert_id,
            severity=raised.alert.severity,
            duplicate=False,
        ),
        True,
    )
