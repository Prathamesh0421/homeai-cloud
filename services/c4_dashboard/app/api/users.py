"""User admin endpoints (contracts §4). Cloud-staff only."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from homeai_common.auth import Principal, require_roles
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.tenants import UserPatchRequest
from app.services import tenant_user_service

router = APIRouter(prefix="/api/v1/users", tags=["users"])

_cs = require_roles("cloud_staff")


@router.patch("/{user_id}", response_model=dict, status_code=status.HTTP_200_OK)
def patch_user(
    user_id: UUID,
    body: UserPatchRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(_cs),
) -> dict:
    result = tenant_user_service.patch_user(db, user_id=user_id, payload=body)
    return {"data": result.model_dump()}
