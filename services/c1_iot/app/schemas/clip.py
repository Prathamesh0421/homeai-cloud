"""Ingest and Clip Library API models (C1 plan §3.3)."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import ClipStatus, MediaKind, UtcDatetime


class IngestOut(BaseModel):
    media_id: str
    status: ClipStatus
    s3_key: str
    duplicate: bool


class ClipOut(BaseModel):
    media_id: str
    house_id: str
    house_name: str | None  # tells same-named feeds of different houses apart
    feed_id: str
    feed_name: str | None
    room_id: str | None
    room_name: str | None
    media_kind: MediaKind
    captured_at: UtcDatetime
    uploaded_at: UtcDatetime
    size: int
    status: ClipStatus
    detection_id: str | None
    top_label: str | None = None  # from C3's ai_detections when available


class ClipDetailOut(ClipOut):
    tenant_id: str
    content_type: str
    s3_key: str
    client_clip_id: str | None
    attempts: int
    error: str | None
    handoff_status: str | None
    top_confidence: float | None = None


class PlaybackUrlOut(BaseModel):
    url: str
    expires_at: UtcDatetime
