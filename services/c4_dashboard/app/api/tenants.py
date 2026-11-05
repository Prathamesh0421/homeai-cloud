"""Tenants admin endpoints (contracts §4). Cloud-staff only."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from homeai_common.auth import Principal, require_roles
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.tenants import TenantCreateRequest, UserCreateRequest
from app.services import tenant_user_service
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])

_cs = require_roles("cloud_staff")


@router.get("", response_model=dict, status_code=status.HTTP_200_OK)
def list_tenants(
    db: Session = Depends(get_db),
    principal: Principal = Depends(_cs),
) -> dict:
    items = [t.model_dump() for t in tenant_user_service.list_tenants(db)]
    return {"data": items}


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_tenant(
    body: TenantCreateRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(_cs),
    authorization: str | None = Header(default=None),
) -> dict:
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
    result = tenant_user_service.create_tenant(
        db,
        payload=body,
        c2_base_url=settings.c2_base_url,
        bearer_token=bearer,
    )
    return {"data": result.model_dump()}


@router.get("/{tenant_id}/users", response_model=dict, status_code=status.HTTP_200_OK)
def list_users(
    tenant_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(_cs),
) -> dict:
    items = [u.model_dump() for u in tenant_user_service.list_users(db, tenant_id)]
    return {"data": items}


@router.post("/{tenant_id}/users", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_user(
    tenant_id: UUID,
    body: UserCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(_cs),
) -> dict:
    result = tenant_user_service.create_user(db, tenant_id=tenant_id, payload=body)
    return {"data": result.model_dump()}
