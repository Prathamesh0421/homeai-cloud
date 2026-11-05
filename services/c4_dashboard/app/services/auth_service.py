"""Auth service: login, lockout, logout, /auth/me, service-token issuance."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models.orm import User
from app.repositories import service_client_repo, user_repo
from app.services import password_hasher, token_denylist
from app.services.jwt_issuer import JwtIssuer, landing_for_role
from app.settings import Settings


def login(
    session: Session,
    *,
    settings: Settings,
    issuer: JwtIssuer,
    email: str,
    password: str,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    user = user_repo.get_by_email(session, email)

    if user is not None and user.locked_until is not None and user.locked_until > now:
        retry_after = int((user.locked_until - now).total_seconds())
        raise ApiError(
            423, "account_locked", "account is locked", {"retry_after": max(retry_after, 1)}
        )

    password_ok = password_hasher.verify_password(password, user.password_hash if user else None)
    user_is_valid = user is not None and user.is_active

    if not user_is_valid or not password_ok:
        if user is not None and user.is_active:
            user_repo.record_failed_attempt(
                session,
                user,
                failure_threshold=settings.lockout_failure_threshold,
                window_seconds=settings.lockout_window_seconds,
                lockout_seconds=settings.lockout_duration_seconds,
                now=now,
            )
            session.commit()
        raise ApiError(401, "invalid_credentials", "invalid credentials")

    # Success: reset counters and issue token.
    user_repo.reset_lockout(session, user)
    user_repo.touch_last_login(session, user, now=now)
    session.commit()

    token, jti, ttl = issuer.issue_user_token(
        user_id=str(user.user_id),
        role=user.role,
        tenant_id=str(user.tenant_id) if user.tenant_id else None,
        house_ids=[str(h) for h in user.house_ids],
        email=user.email,
    )
    return {
        "token": token,
        "expires_in": ttl,
        "landing": landing_for_role(user.role),
        "claims": {
            "sub": str(user.user_id),
            "role": user.role,
            "tenant_id": str(user.tenant_id) if user.tenant_id else None,
            "house_ids": [str(h) for h in user.house_ids],
            "email": user.email,
            "jti": jti,
        },
    }


def logout(session: Session, *, jti: str, exp: int) -> None:
    token_denylist.revoke(
        session,
        UUID(jti),
        datetime.fromtimestamp(exp, tz=UTC),
    )
    session.commit()


def issue_service_token(
    session: Session,
    *,
    issuer: JwtIssuer,
    client_id: str,
    client_secret: str,
    requested_scopes: list[str],
) -> dict:
    client = service_client_repo.get(session, client_id)
    if client is None or not client.is_active:
        raise ApiError(401, "invalid_credentials", "unknown client")
    if not password_hasher.verify_password(client_secret, client.secret_hash):
        raise ApiError(401, "invalid_credentials", "invalid client secret")

    allowed = set(client.scopes)
    requested = set(requested_scopes)
    if not requested.issubset(allowed):
        raise ApiError(
            403,
            "forbidden",
            "scope not allowed",
            {"requested": sorted(requested), "allowed": sorted(allowed)},
        )

    token, _jti, ttl = issuer.issue_service_token(client_id=client_id, scopes=sorted(requested))
    return {"token": token, "expires_in": ttl}


def public_user(user: User) -> dict:
    return {
        "user_id": str(user.user_id),
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        "email": user.email,
        "role": user.role,
        "display_name": user.display_name,
        "house_ids": [str(h) for h in user.house_ids],
        "is_active": user.is_active,
        "last_login_at": user.last_login_at.isoformat().replace("+00:00", "Z")
        if user.last_login_at
        else None,
    }
