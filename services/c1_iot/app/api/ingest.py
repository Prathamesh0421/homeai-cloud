"""Clip ingest (C1 plan §3.3, decision table §4.1): ``POST /ingest/clip`` (multipart)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from homeai_common.auth import Principal
from homeai_common.errors import ErrorEnvelope
from homeai_common.pagination import Envelope, data_response
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_media_repo, get_session, get_storage, staff_or_scope
from app.gateways.s3_media_gateway import MediaStorage
from app.repositories.media_event_repo import MediaEventRepository
from app.schemas.clip import IngestOut
from app.schemas.common import MediaKind
from app.services.ingest_service import ClipUpload, IngestService
from app.settings import Settings

router = APIRouter(prefix="/api/v1", tags=["ingest"])

uploader = staff_or_scope("ingest:write")
CHUNK = 1024 * 1024


async def _read_capped(file: UploadFile, limit: int) -> tuple[bytes, bool]:
    """Read at most ``limit + 1`` bytes; the flag says the file is larger than ``limit``."""
    parts: list[bytes] = []
    size = 0
    while size <= limit:
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        parts.append(chunk)
        size += len(chunk)
    return b"".join(parts), size > limit


@router.post(
    "/ingest/clip",
    response_model=Envelope[IngestOut],
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": Envelope[IngestOut], "description": "duplicate client_clip_id"},
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope, "description": "feed_not_enabled"},
        413: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope, "description": "validation_error, media_kind_mismatch"},
        503: {"model": ErrorEnvelope, "description": "storage_unavailable"},
    },
    summary="Upload a clip from a feed (staff, or service scope ingest:write)",
)
async def ingest_clip(
    response: Response,
    feed_id: uuid.UUID = Form(...),
    media_kind: MediaKind = Form(...),
    captured_at: datetime = Form(..., description="ISO-8601; UTC if no offset"),
    client_clip_id: str | None = Form(None, max_length=100),
    file: UploadFile = File(...),
    principal: Principal = Depends(uploader),
    session: Session = Depends(get_session),
    media: MediaEventRepository = Depends(get_media_repo),
    storage: MediaStorage = Depends(get_storage),
    settings: Settings = Depends(get_app_settings),
):
    data, too_large = await _read_capped(file, settings.max_upload_bytes)
    upload = ClipUpload(
        feed_id=str(feed_id),
        media_kind=media_kind,
        captured_at=captured_at,
        client_clip_id=client_clip_id or None,
        content_type=file.content_type or "",
        data=data,
        too_large=too_large,
    )
    service = IngestService(session, media, storage, max_bytes=settings.max_upload_bytes)
    result = service.ingest(principal, upload)
    if result.duplicate:
        response.status_code = status.HTTP_200_OK
    return data_response(IngestOut(**result.__dict__))
