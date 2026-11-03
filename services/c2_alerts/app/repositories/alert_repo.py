"""Alerts: idempotent insert by detection, scoped reads and conditional status transitions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import String, cast, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.orm import Alert, AlertType
from app.repositories.errors import DuplicateDetectionError, violated_constraint
from app.repositories.scope import Scope

DETECTION_UNIQUE = "alerts_detection_id_key"


class AlertRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_by_detection(self, detection_id: str) -> Alert | None:
        return self.session.scalars(select(Alert).where(Alert.detection_id == detection_id)).first()

    def add(self, alert: Alert) -> Alert:
        """Insert; raises DuplicateDetectionError if the detection already produced an alert.

        Runs in a savepoint so the caller's transaction stays usable and it can re-read the
        existing alert (race-safe idempotency for POST /alerts/evaluate).
        """
        try:
            with self.session.begin_nested():
                self.session.add(alert)
                self.session.flush()
        except IntegrityError as exc:
            if violated_constraint(exc) == DETECTION_UNIQUE:
                raise DuplicateDetectionError from exc
            raise
        return alert

    def get(self, alert_id: str, scope: Scope) -> Alert | None:
        stmt = scope.apply(select(Alert).where(Alert.alert_id == alert_id), Alert)
        return self.session.scalars(stmt).first()

    def list(
        self,
        scope: Scope,
        *,
        statuses: Sequence[str] | None = None,
        severity: str | None = None,
        alert_type_code: str | None = None,
        house_id: str | None = None,
        from_: datetime | None = None,
        to: datetime | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[Alert], int]:
        """Newest first. ``from_`` inclusive, ``to`` exclusive."""
        stmt = scope.apply(select(Alert), Alert)
        if statuses:
            stmt = stmt.where(Alert.status.in_(statuses))
        if severity is not None:
            stmt = stmt.where(Alert.severity == severity)
        if house_id is not None:
            stmt = stmt.where(Alert.house_id == house_id)
        if from_ is not None:
            stmt = stmt.where(Alert.triggered_at >= from_)
        if to is not None:
            stmt = stmt.where(Alert.triggered_at < to)
        if alert_type_code is not None:
            stmt = stmt.join(AlertType, AlertType.alert_type_id == Alert.alert_type_id).where(
                AlertType.code == alert_type_code
            )

        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        page = stmt.order_by(Alert.triggered_at.desc(), Alert.alert_id).offset(offset).limit(limit)
        return list(self.session.scalars(page).unique()), total

    def stats(
        self,
        scope: Scope,
        group_by: str,
        *,
        from_: datetime,
        to: datetime,
        house_id: str | None = None,
        statuses: Sequence[str] | None = None,
    ) -> list[tuple[str, int]]:
        """``[(key, count)]`` of alerts triggered in ``[from_, to)``.

        Keys: severity value, alert type code, house_id, or UTC day ``YYYY-MM-DD``.
        """
        keys: dict[str, Any] = {
            "severity": Alert.severity,
            "alert_type": AlertType.code,
            "house": cast(Alert.house_id, String),
            "day": func.to_char(func.timezone("UTC", Alert.triggered_at), "YYYY-MM-DD"),
        }
        if group_by not in keys:
            raise ValueError(f"unknown group_by {group_by!r}")
        key = keys[group_by].label("key")
        stmt = (
            select(key, func.count().label("count"))
            .select_from(Alert)
            .where(Alert.triggered_at >= from_, Alert.triggered_at < to)
        )
        if group_by == "alert_type":
            stmt = stmt.join(AlertType, AlertType.alert_type_id == Alert.alert_type_id)
        stmt = scope.apply(stmt, Alert)
        if house_id is not None:
            stmt = stmt.where(Alert.house_id == house_id)
        if statuses:
            stmt = stmt.where(Alert.status.in_(statuses))
        rows = self.session.execute(stmt.group_by(key)).all()
        return [(str(k), int(c)) for k, c in rows]

    def transition(
        self, alert_id: str, from_status: str, to_status: str, at: datetime | None = None
    ) -> bool:
        """``UPDATE ... WHERE status = from_status``; False if someone else moved it first.

        Sets ``acknowledged_at`` on acknowledge and ``resolved_at`` when the alert is closed
        (resolved or false_positive).
        """
        when: Any = at if at is not None else func.now()
        values: dict[str, Any] = {"status": to_status, "updated_at": when}
        if to_status == "acknowledged":
            values["acknowledged_at"] = when
        if to_status in ("resolved", "false_positive"):
            values["resolved_at"] = when
        stmt = (
            update(Alert)
            .where(Alert.alert_id == alert_id, Alert.status == from_status)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        changed = self.session.execute(stmt).rowcount == 1
        if changed:
            existing = self.session.get(Alert, alert_id)
            if existing is not None:
                self.session.refresh(existing)
        return changed
