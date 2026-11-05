"""Tenant + user admin service (contracts §4).

Cloud-staff only. After creating a tenant, best-effort call C2
`POST /api/v1/alert-rules/defaults` forwarding the caller's bearer.
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

import bcrypt
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models.orm import Tenant, User
from app.schemas.tenants import (
    TenantCreateRequest,
    TenantResponse,
    UserCreateRequest,
    UserPatchRequest,
    UserResponse,
)

logger = logging.getLogger(__name__)


def _tenant_response(t: Tenant) -> TenantResponse:
    return TenantResponse(
        tenant_id=str(t.tenant_id),
        name=t.name,
        timezone=t.timezone,
        status=t.status,
        created_at=t.created_at.isoformat() if t.created_at else "",
    )


def _user_response(u: User) -> UserResponse:
    return UserResponse(
        user_id=str(u.user_id),
        tenant_id=str(u.tenant_id) if u.tenant_id else None,
        email=u.email,
        role=u.role,
        display_name=u.display_name,
        house_ids=[str(h) for h in (u.house_ids or [])],
        is_active=u.is_active,
        last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
    )


def list_tenants(session: Session) -> list[TenantResponse]:
    rows = list(session.scalars(select(Tenant).order_by(Tenant.created_at)))
    return [_tenant_response(t) for t in rows]


def create_tenant(
    session: Session,
    *,
    payload: TenantCreateRequest,
    c2_base_url: str,
    bearer_token: str | None,
) -> TenantResponse:
    existing = session.scalars(select(Tenant).where(Tenant.name == payload.name)).first()
    if existing is not None:
        raise ApiError(409, "tenant_exists", "tenant name already in use")

    tenant = Tenant(name=payload.name, timezone=payload.timezone)
    session.add(tenant)
    session.commit()
    session.refresh(tenant)

    _post_c2_defaults(c2_base_url, tenant_id=tenant.tenant_id, bearer_token=bearer_token)
    return _tenant_response(tenant)


def _post_c2_defaults(c2_base_url: str, *, tenant_id: UUID, bearer_token: str | None) -> None:
    """Best-effort: tell C2 to seed default alert rules for the new tenant."""
    if not c2_base_url:
        return
    url = f"{c2_base_url.rstrip('/')}/api/v1/alert-rules/defaults"
    headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}
    try:
        resp = httpx.post(url, json={"tenant_id": str(tenant_id)}, headers=headers, timeout=5.0)
        if resp.status_code >= 400:
            logger.warning(
                "C2 alert-rules/defaults returned %s for tenant %s: %s",
                resp.status_code,
                tenant_id,
                resp.text[:200],
            )
    except Exception as exc:  # network errors, timeouts, etc.
        logger.warning("C2 alert-rules/defaults call failed for tenant %s: %s", tenant_id, exc)


def list_users(session: Session, tenant_id: UUID) -> list[UserResponse]:
    stmt = select(User).where(User.tenant_id == tenant_id).order_by(User.created_at)
    return [_user_response(u) for u in session.scalars(stmt)]


def create_user(
    session: Session,
    *,
    tenant_id: UUID,
    payload: UserCreateRequest,
) -> UserResponse:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise ApiError(404, "not_found", "tenant not found")

    existing = session.scalars(select(User).where(User.email == payload.email.lower())).first()
    if existing is not None:
        raise ApiError(409, "email_exists", "email already registered")

    house_ids = _validate_house_ids(payload.house_ids)

    user = User(
        user_id=uuid4(),
        tenant_id=tenant_id,
        email=payload.email,
        password_hash=bcrypt.hashpw(payload.password.encode(), bcrypt.gensalt()).decode(),
        role=payload.role,
        display_name=payload.display_name,
        house_ids=house_ids,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return _user_response(user)


def patch_user(
    session: Session,
    *,
    user_id: UUID,
    payload: UserPatchRequest,
) -> UserResponse:
    user = session.get(User, user_id)
    if user is None:
        raise ApiError(404, "not_found", "user not found")

    data = payload.model_dump(exclude_unset=True)

    if "role" in data and data["role"] is not None:
        user.role = data["role"]
    if "house_ids" in data and data["house_ids"] is not None:
        user.house_ids = _validate_house_ids(data["house_ids"])
    if "is_active" in data and data["is_active"] is not None:
        user.is_active = data["is_active"]
    if data.get("unlock"):
        user.failed_attempts = 0
        user.first_failed_at = None
        user.locked_until = None
    if "password" in data and data["password"] is not None:
        user.password_hash = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt()).decode()

    session.commit()
    session.refresh(user)
    return _user_response(user)


def _validate_house_ids(house_ids: list[str]) -> list[UUID]:
    """Validate house id format and uniqueness.

    Until C1 exists we accept any UUID-shaped ids (seed houses live in C1, not
    here). When C1 is reachable we would reject houses of another tenant with
    422. For now we only validate UUID format and uniqueness.
    """
    parsed: list[UUID] = []
    seen: set[UUID] = set()
    for hid in house_ids:
        try:
            uid = UUID(str(hid))
        except (ValueError, AttributeError) as exc:
            raise ApiError(422, "bad_house_id", f"invalid house id {hid!r}") from exc
        if uid in seen:
            raise ApiError(422, "bad_house_id", "duplicate house id")
        seen.add(uid)
        parsed.append(uid)
    return parsed
