"""Camera feed API models (C1 plan §3.2)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.common import (
    ClipStatus,
    Connectivity,
    FeedStatus,
    MediaKind,
    Sensitivity,
    UtcDatetime,
    UuidStr,
)

FeedName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
NetworkLabel = Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)]


class FeedConfig(BaseModel):
    capture_interval_s: int = Field(ge=5, le=3600)
    sensitivity: Sensitivity
    network_label: NetworkLabel | None = None


class FeedCreate(BaseModel):
    name: FeedName
    media_kind: MediaKind
    house_id: UuidStr
    room_id: UuidStr | None = None
    config: FeedConfig


class FeedUpdate(BaseModel):
    """Only the fields sent are changed; ``room_id: null`` takes the feed out of its room."""

    name: FeedName | None = None
    room_id: UuidStr | None = None


class FeedStatusUpdate(BaseModel):
    is_enabled: bool


class RecentClip(BaseModel):
    media_id: str
    media_kind: MediaKind
    captured_at: UtcDatetime
    uploaded_at: UtcDatetime
    size: int
    status: ClipStatus
    detection_id: str | None = None


class FeedOut(BaseModel):
    feed_id: str
    tenant_id: str
    house_id: str
    house_name: str
    room_id: str | None
    room_name: str | None
    name: str
    media_kind: MediaKind
    status: FeedStatus
    is_enabled: bool
    connectivity_status: Connectivity
    config: FeedConfig
    config_version: int
    last_clip_at: UtcDatetime | None
    created_at: UtcDatetime
    archived_at: UtcDatetime | None


class FeedDetailOut(FeedOut):
    recent_clips: list[RecentClip] = []


class ConfigResult(BaseModel):
    config_version: int
    config: FeedConfig


class ConfigVersionOut(BaseModel):
    version: int
    capture_interval_s: int
    sensitivity: Sensitivity
    network_label: str | None
    created_by: str
    created_at: UtcDatetime


class FeedStats(BaseModel):
    """Contract 02 §4.6 (read by C4 dashboards)."""

    houses: int
    total: int
    by_status: dict[FeedStatus, int]
    online: int
