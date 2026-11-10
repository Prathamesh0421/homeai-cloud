"""Camera feeds, config versions and feed statistics (C1 plan §3.2).

Route order: ``/feeds/stats`` is declared before ``/feeds/{feed_id}`` (AGENTS.md §3).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from homeai_common.auth import Principal
from homeai_common.errors import ErrorEnvelope
from homeai_common.pagination import Envelope, Page, PageParams, data_response, page_response
from sqlalchemy.orm import Session

from app.api.deps import (
    any_user,
    get_session,
    staff,
    staff_or_scope,
)
from app.repositories.feed_repo import FeedFilters
from app.repositories.scope import Scope
from app.schemas.common import Connectivity, FeedStatus, MediaKind
from app.schemas.feed import (
    ConfigResult,
    ConfigVersionOut,
    FeedConfig,
    FeedCreate,
    FeedDetailOut,
    FeedOut,
    FeedStats,
    FeedStatusUpdate,
    FeedUpdate,
)
from app.services.feed_service import FeedService

router = APIRouter(prefix="/api/v1", tags=["camera feeds"])

ERRORS = {
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}
CONFLICT = {409: {"model": ErrorEnvelope, "description": "room_required"}}

stats_reader = staff_or_scope("feeds:read")


def _service(session: Session = Depends(get_session)) -> FeedService:
    return FeedService(session)


def _id(value: uuid.UUID | None) -> str | None:
    return str(value) if value else None


@router.get(
    "/feeds/stats",
    response_model=Envelope[FeedStats],
    responses=ERRORS,
    summary="Feed counts for dashboards (contract §4.6; staff or service scope feeds:read)",
)
def feed_stats(
    tenant_id: uuid.UUID | None = Query(None, description="cloud_staff / service only"),
    house_id: uuid.UUID | None = Query(None),
    principal: Principal = Depends(stats_reader),
    service: FeedService = Depends(_service),
):
    scope = Scope.for_principal(principal, _id(tenant_id))
    return data_response(service.stats(scope, _id(house_id)))


@router.get("/feeds", response_model=Page[FeedOut], responses=ERRORS, summary="List feeds")
def list_feeds(
    params: PageParams = Depends(),
    house_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
    media_kind: MediaKind | None = None,
    status_: FeedStatus | None = Query(None, alias="status"),
    connectivity_status: Connectivity | None = None,
    is_enabled: bool | None = None,
    include_archived: bool = False,
    tenant_id: uuid.UUID | None = Query(None, description="cloud_staff only"),
    principal: Principal = Depends(any_user),
    service: FeedService = Depends(_service),
):
    filters = FeedFilters(
        house_id=_id(house_id),
        room_id=_id(room_id),
        media_kind=media_kind,
        status=status_,
        connectivity_status=connectivity_status,
        is_enabled=is_enabled,
        include_archived=include_archived,
    )
    scope = Scope.for_principal(principal, _id(tenant_id))
    items, total = service.list_feeds(scope, filters, offset=params.offset, limit=params.limit)
    return page_response(items, total, params)


@router.post(
    "/feeds",
    response_model=Envelope[FeedOut],
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
    summary="Register a feed (provisioned, disabled, config v1)",
)
def create_feed(
    body: FeedCreate,
    principal: Principal = Depends(staff),
    service: FeedService = Depends(_service),
):
    return data_response(service.create_feed(principal, body))


@router.get(
    "/feeds/{feed_id}",
    response_model=Envelope[FeedDetailOut],
    responses=ERRORS,
    summary="Get a feed with its last 5 clips",
)
def get_feed(
    feed_id: uuid.UUID,
    principal: Principal = Depends(any_user),
    service: FeedService = Depends(_service),
):
    return data_response(service.get_feed(str(feed_id), Scope.for_principal(principal)))


@router.patch(
    "/feeds/{feed_id}",
    response_model=Envelope[FeedOut],
    responses={**ERRORS, **CONFLICT},
    summary="Rename a feed or move it to another room",
)
def update_feed(
    feed_id: uuid.UUID,
    body: FeedUpdate,
    principal: Principal = Depends(staff),
    service: FeedService = Depends(_service),
):
    return data_response(service.update_feed(str(feed_id), Scope.for_principal(principal), body))


@router.patch(
    "/feeds/{feed_id}/status",
    response_model=Envelope[FeedOut],
    responses={**ERRORS, **CONFLICT},
    summary="Enable or disable a feed (enable needs a room: 409 room_required)",
)
def set_feed_status(
    feed_id: uuid.UUID,
    body: FeedStatusUpdate,
    principal: Principal = Depends(staff),
    service: FeedService = Depends(_service),
):
    scope = Scope.for_principal(principal)
    return data_response(service.set_enabled(str(feed_id), scope, body.is_enabled))


@router.delete(
    "/feeds/{feed_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=ERRORS,
    summary="Archive a feed (disabled, kept for history)",
)
def archive_feed(
    feed_id: uuid.UUID,
    principal: Principal = Depends(staff),
    service: FeedService = Depends(_service),
):
    service.archive(str(feed_id), Scope.for_principal(principal))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- config versions (C1-05) ----------------------------------------------------------------


@router.put(
    "/feeds/{feed_id}/config",
    response_model=Envelope[ConfigResult],
    responses=ERRORS,
    summary="Change the capture config (writes version n+1)",
)
def put_config(
    feed_id: uuid.UUID,
    body: FeedConfig,
    principal: Principal = Depends(staff),
    service: FeedService = Depends(_service),
):
    scope = Scope.for_principal(principal)
    return data_response(service.put_config(str(feed_id), scope, body, principal.sub))


@router.get(
    "/feeds/{feed_id}/config-versions",
    response_model=Envelope[list[ConfigVersionOut]],
    responses=ERRORS,
    summary="Config versions, newest first",
)
def list_config_versions(
    feed_id: uuid.UUID,
    principal: Principal = Depends(staff),
    service: FeedService = Depends(_service),
):
    return data_response(service.list_versions(str(feed_id), Scope.for_principal(principal)))


@router.post(
    "/feeds/{feed_id}/config-versions/{version}/restore",
    response_model=Envelope[ConfigResult],
    responses=ERRORS,
    summary="Restore an old config version (copied into version n+1)",
)
def restore_config_version(
    feed_id: uuid.UUID,
    version: int,
    principal: Principal = Depends(staff),
    service: FeedService = Depends(_service),
):
    scope = Scope.for_principal(principal)
    return data_response(service.restore_version(str(feed_id), scope, version, principal.sub))
