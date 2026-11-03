"""Alert types (seeded by migration 0002; read-only at runtime)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import AlertType


class AlertTypeRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[AlertType]:
        return list(self.session.scalars(select(AlertType).order_by(AlertType.alert_type_id)))

    def get_by_code(self, code: str) -> AlertType | None:
        return self.session.scalars(select(AlertType).where(AlertType.code == code)).first()
