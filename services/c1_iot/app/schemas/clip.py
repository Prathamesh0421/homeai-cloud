"""Ingest and Clip Library API models (C1 plan §3.3)."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import ClipStatus


class IngestOut(BaseModel):
    media_id: str
    status: ClipStatus
    s3_key: str
    duplicate: bool
