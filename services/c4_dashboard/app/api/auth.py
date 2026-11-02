"""Auth endpoints: login, logout, /auth/me, /auth/revoked (contracts §2, §4.7)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_jwt_issuer
from app.errors import ApiError
from app.gateways.house_reader import fetch_house_names
from app.repositories import user_repo
from app.schemas.auth import (
    AuthMeEnvelope,
    HouseRef,
    LoginEnvelope,
    LoginRequest,
    RevokedListEnvelope,
)
from app.services import auth_service, token_denylist
from app.services.jwt_issuer import JwtIssuer
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _decode_unverified(token: str) -> dict:
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except jwt.InvalidTokenError as exc:
        raise ApiError(401, "unauthorized", "malformed token") from exc


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "unauthorized", "missing bearer token")
    return authorization.split(" ", 1)[1].strip()


@router.post("/login", response_model=LoginEnvelope, status_code=status.HTTP_200_OK)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    issuer: JwtIssuer = Depends(get_jwt_issuer),
) -> dict:
    result = auth_service.login(
        db,
        settings=settings,
        issuer=issuer,
        email=body.email,
        password=body.password,
    )
    return {"data": result}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    issuer: JwtIssuer = Depends(get_jwt_issuer),
) -> None:
    token = _bearer(authorization)
    claims = _decode_unverified(token)
    jti = claims.get("jti")
    exp = claims.get("exp")
    if not jti or exp is None:
        raise ApiError(401, "unauthorized", "missing jti or exp")
    auth_service.logout(db, jti=str(jti), exp=int(exp))


@router.get("/me", response_model=AuthMeEnvelope, status_code=status.HTTP_200_OK)
def me(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    token = _bearer(authorization)
    # Strict verification: signature + revocation.
    from homeai_common.auth import verify_token

    revoked = token_denylist.list_revoked_since(db, datetime.fromtimestamp(0, tz=UTC))
    principal = verify_token(token, revoked_jtis=revoked)
    if not principal.is_user:
        raise ApiError(403, "forbidden", "service tokens cannot call /auth/me")

    user = user_repo.get_by_id(db, UUID(principal.sub))
    if user is None:
        raise ApiError(401, "unauthorized", "user not found")

    house_uuids = [UUID(h) for h in principal.house_ids]
    names = fetch_house_names(db.bind, house_uuids) if house_uuids else {}
    houses = [HouseRef(house_id=str(h), name=names.get(h)) for h in house_uuids]
    return {
        "data": {"user": auth_service.public_user(user), "houses": [h.model_dump() for h in houses]}
    }


@router.get("/revoked", response_model=RevokedListEnvelope, status_code=status.HTTP_200_OK)
def revoked(
    since: str | None = None,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    token = _bearer(authorization)
    # Any valid service token may call this (used by other services to refresh their cache).
    from homeai_common.auth import verify_token

    principal = verify_token(token, revoked_jtis=set())
    if not principal.is_service:
        raise ApiError(403, "forbidden", "service token required")

    since_dt = _parse_since(since)
    jti_list = token_denylist.list_revoked_since(db, since_dt)
    return {"data": {"jti": jti_list}}


def _parse_since(since: str | None) -> datetime:
    if not since:
        return datetime.fromtimestamp(0, tz=UTC)
    try:
        dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(
            422,
            "validation_error",
            "since must be ISO-8601",
            [{"field": "since", "issue": "bad format"}],
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
