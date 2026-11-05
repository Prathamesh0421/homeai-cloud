"""Emergency contact endpoints (contracts §3)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from homeai_common.auth import Principal, assert_house, current_principal
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.errors import ApiError
from app.schemas.settings import (
    ContactCreateRequest,
    ContactPatchRequest,
    ContactReorderRequest,
)
from app.services import contact_service, settings_service

router = APIRouter(tags=["contacts"])


def _house_tenant_id(session: Session, house_id: UUID) -> UUID | None:
    row = settings_service.settings_repo.get(session, house_id)
    return row.tenant_id if row else None


def _resolve_tenant(session: Session, house_id: UUID, principal: Principal) -> UUID:
    tenant_id = _house_tenant_id(session, house_id)
    if tenant_id is not None:
        return tenant_id
    if principal.is_user and principal.tenant_id:
        return UUID(principal.tenant_id)
    raise ApiError(422, "tenant_required", "cannot determine tenant for house")


@router.get(
    "/api/v1/houses/{house_id}/emergency-contacts",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
def list_contacts(
    house_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> dict:
    assert_house(principal, str(house_id), _house_tenant_id(db, house_id))
    items = [c.model_dump() for c in contact_service.list_contacts(db, house_id)]
    return {"data": items}


@router.post(
    "/api/v1/houses/{house_id}/emergency-contacts",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
def create_contact(
    house_id: UUID,
    body: ContactCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> dict:
    assert_house(principal, str(house_id), _house_tenant_id(db, house_id))
    tenant_id = _resolve_tenant(db, house_id, principal)
    result = contact_service.create_contact(
        db, house_id=house_id, tenant_id=tenant_id, payload=body
    )
    return {"data": result.model_dump()}


@router.put(
    "/api/v1/houses/{house_id}/emergency-contacts/order",
    status_code=status.HTTP_204_NO_CONTENT,
)
def reorder_contacts(
    house_id: UUID,
    body: ContactReorderRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> None:
    assert_house(principal, str(house_id), _house_tenant_id(db, house_id))
    contact_service.reorder_contacts(db, house_id=house_id, contact_ids=body.contact_ids)


@router.patch(
    "/api/v1/emergency-contacts/{contact_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
def patch_contact(
    contact_id: UUID,
    body: ContactPatchRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> dict:
    contact = contact_service.contact_repo.get(db, contact_id)
    if contact is None:
        raise ApiError(404, "not_found", "contact not found")
    assert_house(principal, str(contact.house_id), contact.tenant_id)
    result = contact_service.patch_contact(db, contact_id=contact_id, payload=body)
    return {"data": result.model_dump()}


@router.delete(
    "/api/v1/emergency-contacts/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_contact(
    contact_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> None:
    contact = contact_service.contact_repo.get(db, contact_id)
    if contact is None:
        raise ApiError(404, "not_found", "contact not found")
    assert_house(principal, str(contact.house_id), contact.tenant_id)
    contact_service.delete_contact(db, contact_id=contact_id)
