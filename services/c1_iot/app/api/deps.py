"""FastAPI dependencies shared by C1 routers (tests override these).

Access legend from the C1 plan §3: **S** = iot_staff (own tenant) or cloud_staff (any tenant),
**O** = house_owner (own houses, read-only). Some endpoints also take a service token scope.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request
from homeai_common import db
from homeai_common.auth import Principal, current_principal, require_roles

from app.settings import Settings

STAFF_ROLES = frozenset({"iot_staff", "cloud_staff"})
READER_ROLES = frozenset({"house_owner", "iot_staff", "cloud_staff"})

# Read/write session as c1_app.
get_session = db.get_session

# S: writes. S + O: reads.
staff = require_roles(*STAFF_ROLES)
any_user = require_roles(*READER_ROLES)


def get_app_settings(request: Request) -> Settings:
    """The Settings ``create_app`` was built with (tests pass their own)."""
    return request.app.state.settings


def get_clock() -> Callable[[], datetime]:
    """Current UTC time source (tests override it)."""
    return lambda: datetime.now(UTC)


def _forbidden(message: str) -> HTTPException:
    return HTTPException(status_code=403, detail={"code": "forbidden", "message": message})


def staff_or_scope(scope: str) -> Callable[..., Principal]:
    """S users, or a service token carrying ``scope``."""

    def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.is_user and principal.role in STAFF_ROLES:
            return principal
        if principal.is_service and principal.has_scope(scope):
            return principal
        raise _forbidden(f"iot_staff, cloud_staff or scope {scope!r} required")

    return _dep


def user_or_scope(scope: str) -> Callable[..., Principal]:
    """S or O users, or a service token carrying ``scope``."""

    def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.is_user and principal.role in READER_ROLES:
            return principal
        if principal.is_service and principal.has_scope(scope):
            return principal
        raise _forbidden(f"a user token or scope {scope!r} required")

    return _dep
