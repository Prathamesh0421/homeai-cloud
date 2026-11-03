"""C3 -> C2 ``POST /alerts/evaluate`` payloads (contract 02 §4.3)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UuidStr


class EvaluateLabel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    confidence: float = Field(ge=0, le=1)


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detection_id: UuidStr
    media_id: UuidStr
    house_id: UuidStr
    room_id: UuidStr | None = None
    top_label: str
    top_confidence: float = Field(ge=0, le=1)
    labels: list[EvaluateLabel] = Field(default_factory=list)
    detected_at: datetime


NoAlertReason = Literal[
    "service_disabled", "no_rule_match", "below_threshold", "room_mismatch", "quiet_hours"
]


class EvaluateResult(BaseModel):
    decision: Literal["alert", "no_alert"]
    alert_id: str | None = None
    severity: Literal["critical", "high", "medium", "low"] | None = None
    duplicate: bool | None = None
    reason: NoAlertReason | None = None
