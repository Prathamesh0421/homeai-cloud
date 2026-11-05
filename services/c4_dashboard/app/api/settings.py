"""Settings endpoints (contracts §3)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from homeai_common.auth import Principal, assert_house, current_principal
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.errors import ApiError
from app.schemas.settings import SettingsUpsertRequest
from app.services import settings_service

router = APIRouter(prefix="/api/v1/houses", tags=["settings"])


def _house_tenant_id(session: Session, house_id: UUID) -> UUID | None:
    """Best-effort: read tenant_id from an existing settings row, else None.

    C1 (houses table) is not yet available, so when no settings row exists we
    cannot know the tenant. assert_house still allows cloud_staff and house
    owners (by house_ids membership) without it.
    """
    row = settings_service.settings_repo.get(session, house_id)
    return row.tenant_id if row else None


@router.get("/{house_id}/settings", response_model=dict, status_code=status.HTTP_200_OK)
def get_settings(
    house_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> dict:
    assert_house(principal, str(house_id), _house_tenant_id(db, house_id))
    result = settings_service.get_settings(db, house_id)
    return {"data": result.model_dump()}


@router.put("/{house_id}/settings", response_model=dict, status_code=status.HTTP_200_OK)
def put_settings(
    house_id: UUID,
    body: SettingsUpsertRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> dict:
    tenant_id = _house_tenant_id(db, house_id)
    assert_house(principal, str(house_id), tenant_id)

    # For an upsert we need a tenant_id for the new row.
    if tenant_id is None:
        if principal.is_user and principal.tenant_id:
            tenant_id = UUID(principal.tenant_id)
        elif principal.is_cloud_staff():
            raise ApiError(
                422,
                "tenant_required",
                "cloud staff must create settings for a house with an existing tenant; "
                "create the tenant/house first",
            )
        else:
            raise ApiError(422, "tenant_required", "cannot determine tenant for house")

    if principal.is_user and principal.tenant_id and tenant_id != UUID(principal.tenant_id):
        raise ApiError(403, "forbidden", "house belongs to another tenant")

    result = settings_service.upsert_settings(
        db,
        house_id=house_id,
        tenant_id=tenant_id,
        updated_by=UUID(principal.sub),
        payload=body,
    )
    return {"data": result.model_dump()}
