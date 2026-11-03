"""Alert status history (append-only audit trail)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import AlertStatusHistory


class HistoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(
        self,
        alert_id: str,
        from_status: str | None,
        to_status: str,
        actor_id: str,
        actor_role: str,
        note: str | None = None,
    ) -> AlertStatusHistory:
        entry = AlertStatusHistory(
            alert_id=alert_id,
            from_status=from_status,
            to_status=to_status,
            actor_id=actor_id,
            actor_role=actor_role,
            note=note,
        )
        self.session.add(entry)
        self.session.flush()
        return entry

    def list_for_alert(self, alert_id: str) -> list[AlertStatusHistory]:
        stmt = (
            select(AlertStatusHistory)
            .where(AlertStatusHistory.alert_id == alert_id)
            .order_by(AlertStatusHistory.changed_at, AlertStatusHistory.history_id)
        )
        return list(self.session.scalars(stmt))
