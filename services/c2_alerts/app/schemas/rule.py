"""Alert type and alert rule API models (docs/components/C2_ALERT_TRACKING.md §3)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import UuidStr

HomeLabel = Literal[
    "smoke_alarm", "distress_sound", "glass_break", "fall_indicator", "cough", "speech", "dog"
]
Severity = Literal["critical", "high", "medium", "low"]


class AlertTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    category: str
    service_code: str
    trigger_label: str
    default_severity: Severity
    default_min_confidence: float


def _confidence_2dp(value: float | None) -> float | None:
    # Stored as NUMERIC(3,2): reject values Postgres would silently round.
    if value is not None and round(value, 2) != value:
        raise ValueError("must have at most 2 decimal places")
    return value


def _dedupe(labels: list[str]) -> list[str]:
    return list(dict.fromkeys(labels))


class RuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UuidStr | None = Field(
        default=None, description="Required for a tenant-wide rule (no house_id)."
    )
    house_id: UuidStr | None = Field(default=None, description="Omit for a tenant-wide default.")
    alert_type_code: str
    trigger_labels: list[HomeLabel] = Field(min_length=1)
    min_confidence: float | None = Field(
        default=None, ge=0, le=1, description="Defaults to the alert type's default."
    )
    room_id: UuidStr | None = Field(default=None, description="Must belong to house_id.")
    severity: Severity | None = Field(
        default=None, description="Overrides the alert type's default severity."
    )
    is_enabled: bool = True

    _labels = field_validator("trigger_labels")(_dedupe)
    _conf = field_validator("min_confidence")(_confidence_2dp)


class RuleUpdate(BaseModel):
    """Fields to change; omitted fields keep their value. ``null`` clears room/severity."""

    model_config = ConfigDict(extra="forbid")

    trigger_labels: list[HomeLabel] | None = Field(default=None, min_length=1)
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    room_id: UuidStr | None = None
    severity: Severity | None = None
    is_enabled: bool | None = None

    _labels = field_validator("trigger_labels")(lambda v: _dedupe(v) if v is not None else v)
    _conf = field_validator("min_confidence")(_confidence_2dp)


class RuleOut(BaseModel):
    rule_id: str
    tenant_id: str
    house_id: str | None
    scope: Literal["tenant_default", "house"]
    alert_type_code: str
    alert_type_name: str
    trigger_labels: list[str]
    min_confidence: float
    room_id: str | None
    severity: Severity | None
    effective_severity: Severity
    is_enabled: bool
    version: int
    false_positive_count_30d: int = 0
    created_by: str
    created_at: datetime
    updated_at: datetime


class DefaultsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UuidStr


class DefaultsResult(BaseModel):
    created: int
