"""Clip Library (C1 plan §3.3): list, detail, presigned playback URL."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from homeai_common.auth import Principal
from homeai_common.errors import ErrorEnvelope
from homeai_common.pagination import Envelope, Page, PageParams, data_response, page_response
from pymongo.collection import Collection
from sqlalchemy.orm import Session

from app.api.deps import (
    any_user,
    get_app_settings,
    get_detections,
    get_media_repo,
    get_session,
    get_storage,
    user_or_scope,
)
from app.gateways.s3_media_gateway import MediaStorage
from app.repositories.media_event_repo import MediaEventRepository
from app.repositories.scope import Scope
from app.schemas.clip import ClipDetailOut, ClipOut, PlaybackUrlOut
from app.schemas.common import ClipStatus
from app.services.clip_library_service import ClipFilters, ClipLibraryService
from app.settings import Settings

router = APIRouter(prefix="/api/v1", tags=["clips"])

ERRORS = {
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}
playback_reader = user_or_scope("clips:playback")


def _service(
    session: Session = Depends(get_session),
    media: MediaEventRepository = Depends(get_media_repo),
    storage: MediaStorage = Depends(get_storage),
    detections: Collection | None = Depends(get_detections),
    settings: Settings = Depends(get_app_settings),
) -> ClipLibraryService:
    return ClipLibraryService(
        session, media, storage, detections=detections, presign_ttl_s=settings.presign_ttl_s
    )


def _id(value: uuid.UUID | None) -> str | None:
    return str(value) if value else None


@router.get("/clips", response_model=Page[ClipOut], responses=ERRORS, summary="Clip Library")
def list_clips(
    params: PageParams = Depends(),
    house_id: uuid.UUID | None = None,
    feed_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
    status: ClipStatus | None = None,
    from_: datetime | None = Query(None, alias="from", description="captured_at >= from"),
    to: datetime | None = Query(None, description="captured_at < to"),
    tenant_id: uuid.UUID | None = Query(None, description="cloud_staff only"),
    principal: Principal = Depends(any_user),
    service: ClipLibraryService = Depends(_service),
):
    filters = ClipFilters(
        house_id=_id(house_id),
        feed_id=_id(feed_id),
        room_id=_id(room_id),
        status=status,
        from_=from_,
        to=to,
    )
    scope = Scope.for_principal(principal, _id(tenant_id))
    items, total = service.list_clips(scope, filters, offset=params.offset, limit=params.limit)
    return page_response(items, total, params)


@router.get(
    "/clips/{media_id}",
    response_model=Envelope[ClipDetailOut],
    responses=ERRORS,
    summary="One clip with its top label (if C3 analysed it)",
)
def get_clip(
    media_id: uuid.UUID,
    principal: Principal = Depends(any_user),
    service: ClipLibraryService = Depends(_service),
):
    return data_response(service.get_clip(str(media_id), Scope.for_principal(principal)))


@router.get(
    "/clips/{media_id}/playback-url",
    response_model=Envelope[PlaybackUrlOut],
    responses={**ERRORS, 503: {"model": ErrorEnvelope}},
    summary="15-minute presigned URL (users in scope, or service scope clips:playback)",
)
def playback_url(
    media_id: uuid.UUID,
    principal: Principal = Depends(playback_reader),
    service: ClipLibraryService = Depends(_service),
):
    return data_response(service.playback_url(str(media_id), Scope.for_principal(principal)))
