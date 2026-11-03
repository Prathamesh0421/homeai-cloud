"""Public alert view for emergency contacts (no login; no owner or contact details)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.alert import AlertStatus, Severity


class AlertViewLabel(BaseModel):
    label: str
    confidence: float


class AlertView(BaseModel):
    alert_type_name: str
    severity: Severity
    status: AlertStatus
    house_name: str | None
    room_name: str | None
    triggered_at: datetime
    labels: list[AlertViewLabel]
    clip_url: str | None
    expires_at: datetime
