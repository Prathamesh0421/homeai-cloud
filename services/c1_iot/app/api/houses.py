"""Houses and rooms (C1 plan §3.1). Staff manage them; owners read their own houses."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from homeai_common.auth import Principal
from homeai_common.errors import ErrorEnvelope
from homeai_common.pagination import Envelope, Page, PageParams, data_response, page_response
from sqlalchemy.orm import Session

from app.api.deps import any_user, get_app_settings, get_session, staff
from app.repositories.scope import Scope
from app.schemas.house import HouseCreate, HouseOut, HouseUpdate, RoomCreate, RoomOut, RoomUpdate
from app.services.house_service import HouseService
from app.settings import Settings

router = APIRouter(prefix="/api/v1", tags=["houses and rooms"])

ERRORS = {
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}
CONFLICT = {409: {"model": ErrorEnvelope}}


def _service(
    session: Session = Depends(get_session), settings: Settings = Depends(get_app_settings)
) -> HouseService:
    return HouseService(session, demo_mode=settings.demo_mode)


# --- houses -------------------------------------------------------------------------------


@router.get("/houses", response_model=Page[HouseOut], responses=ERRORS, summary="List houses")
def list_houses(
    params: PageParams = Depends(),
    q: str | None = Query(None, max_length=80, description="Name contains (case-insensitive)"),
    tenant_id: uuid.UUID | None = Query(None, description="cloud_staff only: one tenant"),
    principal: Principal = Depends(any_user),
    service: HouseService = Depends(_service),
):
    scope = Scope.for_principal(principal, str(tenant_id) if tenant_id else None)
    items, total = service.list_houses(scope, q=q, offset=params.offset, limit=params.limit)
    return page_response(items, total, params)


@router.post(
    "/houses",
    response_model=Envelope[HouseOut],
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
    summary="Create a house",
)
def create_house(
    body: HouseCreate,
    principal: Principal = Depends(staff),
    service: HouseService = Depends(_service),
):
    return data_response(service.create_house(principal, body))


@router.get(
    "/houses/{house_id}",
    response_model=Envelope[HouseOut],
    responses=ERRORS,
    summary="Get a house with its room and feed counts",
)
def get_house(
    house_id: uuid.UUID,
    principal: Principal = Depends(any_user),
    service: HouseService = Depends(_service),
):
    return data_response(service.get_house(str(house_id), Scope.for_principal(principal)))


@router.patch(
    "/houses/{house_id}",
    response_model=Envelope[HouseOut],
    responses=ERRORS,
    summary="Update a house",
)
def update_house(
    house_id: uuid.UUID,
    body: HouseUpdate,
    principal: Principal = Depends(staff),
    service: HouseService = Depends(_service),
):
    return data_response(service.update_house(str(house_id), Scope.for_principal(principal), body))


@router.delete(
    "/houses/{house_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={**ERRORS, **CONFLICT},
    summary="Delete a house (409 house_not_empty while a feed is enabled)",
)
def delete_house(
    house_id: uuid.UUID,
    principal: Principal = Depends(staff),
    service: HouseService = Depends(_service),
):
    service.delete_house(str(house_id), Scope.for_principal(principal))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- rooms --------------------------------------------------------------------------------


@router.get(
    "/houses/{house_id}/rooms",
    response_model=Envelope[list[RoomOut]],
    responses=ERRORS,
    summary="List a house's rooms",
)
def list_rooms(
    house_id: uuid.UUID,
    principal: Principal = Depends(any_user),
    service: HouseService = Depends(_service),
):
    return data_response(service.list_rooms(str(house_id), Scope.for_principal(principal)))


@router.post(
    "/houses/{house_id}/rooms",
    response_model=Envelope[RoomOut],
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
    summary="Add a room to a house",
)
def create_room(
    house_id: uuid.UUID,
    body: RoomCreate,
    principal: Principal = Depends(staff),
    service: HouseService = Depends(_service),
):
    return data_response(service.create_room(str(house_id), Scope.for_principal(principal), body))


@router.patch(
    "/rooms/{room_id}", response_model=Envelope[RoomOut], responses=ERRORS, summary="Rename a room"
)
def update_room(
    room_id: uuid.UUID,
    body: RoomUpdate,
    principal: Principal = Depends(staff),
    service: HouseService = Depends(_service),
):
    return data_response(service.update_room(str(room_id), Scope.for_principal(principal), body))


@router.delete(
    "/rooms/{room_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={**ERRORS, **CONFLICT},
    summary="Delete a room (409 room_in_use while a feed is in it)",
)
def delete_room(
    room_id: uuid.UUID,
    principal: Principal = Depends(staff),
    service: HouseService = Depends(_service),
):
    service.delete_room(str(room_id), Scope.for_principal(principal))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
