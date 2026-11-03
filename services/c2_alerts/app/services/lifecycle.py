"""Alert lifecycle: raise once per detection, then acknowledge / resolve / false positive.

State machine (C2 plan §4.2): open -> acknowledged -> resolved; open|acknowledged ->
false_positive. Every change appends to ``alert_status_history`` in the same transaction.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeai_common.auth import Principal, assert_house
from homeai_common.errors import ApiError
from sqlalchemy.orm import Session

from app.constants import SYSTEM_ACTOR
from app.gateways.types import Detection
from app.models.orm import Alert
from app.repositories.alert_repo import AlertRepository
from app.repositories.errors import DuplicateDetectionError
from app.repositories.history_repo import HistoryRepository
from app.repositories.scope import Scope
from app.services.rule_engine import Decision

# action -> (allowed from-statuses, to-status)
TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "acknowledge": (frozenset({"open"}), "acknowledged"),
    "resolve": (frozenset({"acknowledged"}), "resolved"),
    "false_positive": (frozenset({"open", "acknowledged"}), "false_positive"),
}


def allowed_actions(status: str) -> list[str]:
    return [action for action, (sources, _) in TRANSITIONS.items() if status in sources]


def invalid_state(from_status: str, to_status: str) -> ApiError:
    return ApiError(
        409,
        "invalid_state",
        f"cannot move an alert from {from_status} to {to_status}",
        {"from": from_status, "to": to_status},
    )


@dataclass(frozen=True)
class Raised:
    alert: Alert
    duplicate: bool


@dataclass
class AlertLifecycleService:
    session: Session

    @property
    def alerts(self) -> AlertRepository:
        return AlertRepository(self.session)

    @property
    def history(self) -> HistoryRepository:
        return HistoryRepository(self.session)

    def raise_alert(self, decision: Decision, detection: Detection, tenant_id: str) -> Raised:
        """Insert the alert + ``null -> open`` history by ``system``; commit.

        If another request raised an alert for this detection first (unique detection_id),
        return that one with ``duplicate=True`` instead.
        """
        rule = decision.rule
        if not decision.is_alert or rule is None or decision.severity is None:
            raise ValueError("raise_alert needs an alert decision")
        alert = Alert(
            tenant_id=tenant_id,
            house_id=detection.house_id,
            room_id=detection.room_id,
            alert_type_id=rule.alert_type_id,
            rule_id=rule.rule_id,
            detection_id=detection.detection_id,
            media_id=detection.media_id,
            top_label=detection.top_label,
            top_confidence=detection.top_confidence,
            threshold=decision.threshold,
            severity=decision.severity,
        )
        try:
            self.alerts.add(alert)
        except DuplicateDetectionError:
            # The insert ran in a savepoint, so this transaction is still usable; the winner
            # has committed (Postgres waits for it before reporting the unique violation).
            existing = self.alerts.find_by_detection(detection.detection_id)
            if existing is None:  # pragma: no cover - the winner's insert is committed
                raise
            return Raised(existing, duplicate=True)
        self.history.add(alert.alert_id, None, "open", SYSTEM_ACTOR, SYSTEM_ACTOR)
        self.session.commit()
        self.session.refresh(alert)
        return Raised(alert, duplicate=False)

    def transition(
        self, alert_id: str, action: str, principal: Principal, note: str | None = None
    ) -> Alert:
        """Apply ``action``; 404 unknown, 403 not the caller's house, 409 invalid state."""
        sources, to_status = TRANSITIONS[action]
        alert = self.alerts.get(alert_id, Scope.everything())
        if alert is None:
            raise ApiError(404, "not_found", "alert not found")
        assert_house(principal, alert.house_id, alert.tenant_id)

        from_status = alert.status
        if from_status not in sources:
            raise invalid_state(from_status, to_status)
        if not self.alerts.transition(alert_id, from_status, to_status):
            # Someone else changed it between our read and our UPDATE (their commit made our
            # conditional UPDATE match 0 rows). A fresh SELECT sees their status.
            self.session.refresh(alert)
            raise invalid_state(alert.status, to_status)

        self.history.add(
            alert_id,
            from_status,
            to_status,
            principal.sub,
            principal.role or "service",
            note or None,
        )
        self.session.commit()
        self.session.refresh(alert)
        return alert
