"""Alert API models (docs/components/C2_ALERT_TRACKING.md §3)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

AlertStatus = Literal["open", "acknowledged", "resolved", "false_positive"]
Severity = Literal["critical", "high", "medium", "low"]
Action = Literal["acknowledge", "resolve", "false_positive"]

Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class AlertSummary(BaseModel):
    """One row of ``GET /alerts``. Names are null if C1 cannot be reached."""

    alert_id: str
    tenant_id: str
    house_id: str
    house_name: str | None
    room_id: str | None
    room_name: str | None
    alert_type_code: str
    alert_type_name: str
    category: str
    severity: Severity
    status: AlertStatus
    top_label: str
    top_confidence: float
    triggered_at: datetime


class EvidenceLabel(BaseModel):
    label: str
    confidence: float
    source_class: str | None = None
    start_s: float | None = None
    end_s: float | None = None


class EvidenceModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    name: str
    version: str


class Evidence(BaseModel):
    """From C3's ``ai_detections``; if C3 is unavailable, ``labels`` holds only the top label."""

    model_config = ConfigDict(protected_namespaces=())

    detection_id: str
    media_id: str
    labels: list[EvidenceLabel]
    model: EvidenceModel | None
    detection_available: bool
    threshold: float | None = Field(
        description="Effective threshold the alert was raised at (rule + house sensitivity)."
    )


class TimelineEntry(BaseModel):
    from_status: AlertStatus | None
    to_status: AlertStatus
    actor_id: str
    actor_role: str
    note: str | None
    changed_at: datetime


class NotificationOut(BaseModel):
    notification_id: str
    channel: Literal["in_app", "email"]
    contact_id: str | None
    recipient: str | None
    priority: int | None
    status: Literal["queued", "sent", "failed"]
    attempt_count: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None


class AlertDetail(AlertSummary):
    rule_id: str
    detection_id: str
    media_id: str
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    updated_at: datetime
    allowed_actions: list[Action] = Field(
        description="Actions valid in the current status (the UI enables only these)."
    )
    evidence: Evidence
    timeline: list[TimelineEntry]
    notifications: list[NotificationOut]


class NoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Note | None = None


class FalsePositiveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class StatBucket(BaseModel):
    key: str
    count: int
