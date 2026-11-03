"""Alert reads for the API: list, detail (evidence, timeline, notifications) and stats."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeai_common.auth import Principal, assert_house
from homeai_common.errors import ApiError
from sqlalchemy.orm import Session

from app.constants import SEVERITY_RANK
from app.gateways.types import (
    DependencyUnavailableError,
    DetectionReader,
    House,
    HouseReader,
    InvalidDetectionError,
    Room,
)
from app.models.orm import Alert
from app.repositories.alert_repo import AlertRepository
from app.repositories.history_repo import HistoryRepository
from app.repositories.notification_repo import NotificationRepository
from app.repositories.scope import Scope
from app.schemas.alert import (
    AlertDetail,
    AlertSummary,
    Evidence,
    EvidenceLabel,
    EvidenceModel,
    NotificationOut,
    StatBucket,
    TimelineEntry,
)
from app.services.lifecycle import allowed_actions
from app.services.signed_link import SignedLinkService

logger = logging.getLogger(__name__)

MAX_STATS_SPAN = timedelta(days=366)
GROUP_BY = ("severity", "alert_type", "house", "day")


def _invalid(field: str, issue: str) -> ApiError:
    return ApiError(
        422, "validation_error", "request validation failed", [{"field": field, "issue": issue}]
    )


def check_window(from_: datetime | None, to: datetime | None) -> None:
    if from_ is not None and to is not None and from_ >= to:
        raise _invalid("from", "must be before to")


@dataclass
class AlertService:
    session: Session
    houses: HouseReader
    detections: DetectionReader | None
    view_links: SignedLinkService | None = None  # set only in DEMO_MODE (C2 plan §3)

    @property
    def alerts(self) -> AlertRepository:
        return AlertRepository(self.session)

    # --- names (best effort: C1 down must not break alert pages) ------------------------------

    def names(self, alerts: Sequence[Alert]) -> tuple[dict[str, House], dict[str, Room]]:
        try:
            return (
                self.houses.houses(a.house_id for a in alerts),
                self.houses.rooms(a.room_id for a in alerts if a.room_id),
            )
        except DependencyUnavailableError as exc:
            logger.warning("house/room names unavailable", extra={"source": exc.source})
            return {}, {}

    @staticmethod
    def _summary_fields(alert: Alert, houses: dict[str, House], rooms: dict[str, Room]) -> dict:
        house = houses.get(alert.house_id)
        room = rooms.get(alert.room_id) if alert.room_id else None
        t = alert.alert_type
        return {
            "alert_id": alert.alert_id,
            "tenant_id": alert.tenant_id,
            "house_id": alert.house_id,
            "house_name": house.name if house else None,
            "room_id": alert.room_id,
            "room_name": room.name if room else None,
            "alert_type_code": t.code,
            "alert_type_name": t.name,
            "category": t.category,
            "severity": alert.severity,
            "status": alert.status,
            "top_label": alert.top_label,
            "top_confidence": alert.top_confidence,
            "triggered_at": alert.triggered_at,
        }

    # --- list ---------------------------------------------------------------------------------

    def list(
        self,
        scope: Scope,
        *,
        statuses: Sequence[str] | None,
        severity: str | None,
        alert_type_code: str | None,
        house_id: str | None,
        from_: datetime | None,
        to: datetime | None,
        offset: int,
        limit: int,
    ) -> tuple[list[AlertSummary], int]:
        check_window(from_, to)
        rows, total = self.alerts.list(
            scope,
            statuses=statuses,
            severity=severity,
            alert_type_code=alert_type_code,
            house_id=house_id,
            from_=from_,
            to=to,
            offset=offset,
            limit=limit,
        )
        houses, rooms = self.names(rows)
        return [AlertSummary(**self._summary_fields(a, houses, rooms)) for a in rows], total

    # --- detail -------------------------------------------------------------------------------

    def evidence(self, alert: Alert) -> Evidence:
        detection = None
        if self.detections is not None:
            try:
                detection = self.detections.get(alert.detection_id)
            except (DependencyUnavailableError, InvalidDetectionError) as exc:
                logger.warning(
                    "detection unavailable for alert evidence",
                    extra={"alert_id": alert.alert_id, "error": str(exc)[:200]},
                )
        if detection is None:
            return Evidence(
                detection_id=alert.detection_id,
                media_id=alert.media_id,
                labels=[EvidenceLabel(label=alert.top_label, confidence=alert.top_confidence)],
                model=None,
                detection_available=False,
                threshold=alert.threshold,
            )
        return Evidence(
            detection_id=alert.detection_id,
            media_id=alert.media_id,
            labels=[EvidenceLabel(**label.model_dump()) for label in detection.labels],
            model=EvidenceModel(**detection.model.model_dump()) if detection.model else None,
            detection_available=True,
            threshold=alert.threshold,
        )

    def _demo_link(self, alert: Alert, contact_id: str | None) -> str | None:
        if self.view_links is None or contact_id is None:
            return None
        try:
            return self.view_links.link(
                self.view_links.issue(alert.alert_id, contact_id, alert.triggered_at)
            )
        except DependencyUnavailableError:
            return None

    def detail_of(self, alert: Alert) -> AlertDetail:
        houses, rooms = self.names([alert])
        timeline = [
            TimelineEntry(
                from_status=h.from_status,
                to_status=h.to_status,
                actor_id=h.actor_id,
                actor_role=h.actor_role,
                note=h.note,
                changed_at=h.changed_at,
            )
            for h in HistoryRepository(self.session).list_for_alert(alert.alert_id)
        ]
        notifications = [
            NotificationOut(
                notification_id=n.notification_id,
                channel=n.channel,
                contact_id=n.contact_id,
                recipient=n.recipient,
                priority=n.priority,
                status=n.status,
                attempt_count=n.attempt_count,
                last_error=n.last_error,
                created_at=n.created_at,
                sent_at=n.sent_at,
                view_link=self._demo_link(alert, n.contact_id) if n.channel == "email" else None,
            )
            for n in NotificationRepository(self.session).list_for_alert(alert.alert_id)
        ]
        return AlertDetail(
            **self._summary_fields(alert, houses, rooms),
            rule_id=alert.rule_id,
            detection_id=alert.detection_id,
            media_id=alert.media_id,
            acknowledged_at=alert.acknowledged_at,
            resolved_at=alert.resolved_at,
            updated_at=alert.updated_at,
            allowed_actions=allowed_actions(alert.status),
            evidence=self.evidence(alert),
            timeline=timeline,
            notifications=notifications,
        )

    def detail(self, alert_id: str, principal: Principal) -> AlertDetail:
        """404 if unknown, 403 if not the caller's house (same checks as the actions)."""
        alert = self.alerts.get(alert_id, Scope.everything())
        if alert is None:
            raise ApiError(404, "not_found", "alert not found")
        assert_house(principal, alert.house_id, alert.tenant_id)
        return self.detail_of(alert)

    # --- stats --------------------------------------------------------------------------------

    def stats(
        self,
        scope: Scope,
        group_by: str,
        *,
        from_: datetime,
        to: datetime,
        house_id: str | None,
        statuses: Sequence[str] | None,
    ) -> list[StatBucket]:
        check_window(from_, to)
        if to - from_ > MAX_STATS_SPAN:
            raise _invalid("to", "the window may span at most 366 days")
        rows = self.alerts.stats(
            scope, group_by, from_=from_, to=to, house_id=house_id, statuses=statuses
        )
        if group_by == "day":
            rows.sort(key=lambda kc: kc[0])
        elif group_by == "severity":
            rows.sort(key=lambda kc: -SEVERITY_RANK.get(kc[0], 0))
        else:
            rows.sort(key=lambda kc: (-kc[1], kc[0]))
        return [StatBucket(key=k, count=c) for k, c in rows]
