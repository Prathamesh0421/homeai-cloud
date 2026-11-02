"""JWT verification shared by every service.

Implements contracts §2.4 of docs/02_CONTRACTS.md:
  1. Fetch JWKS (cache 10 min, refetch on unknown kid).
  2. Verify RS256 signature, iss=homeai-c4, aud=homeai, exp (60s leeway).
  3. For typ=user: reject if jti is revoked (C4 enforces strictly; others use cached list).
  4. Build a Principal and pass it to handlers.

This module is intentionally framework-light: it exposes the verification
function and a FastAPI dependency. C4 imports it from the same package; other
services install `homeai-common` as a path dependency.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, status

ISSUER = "homeai-c4"
AUDIENCE = "homeai"
CLOCK_LEEWAY_SECONDS = 60
JWKS_CACHE_TTL_SECONDS = 600


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, derived from a verified JWT."""

    kind: str  # "user" or "service"
    sub: str  # user_id or client_id
    role: str | None
    tenant_id: str | None
    house_ids: tuple[str, ...] = field(default_factory=tuple)
    scopes: tuple[str, ...] = field(default_factory=tuple)
    jti: str | None = None

    @property
    def is_user(self) -> bool:
        return self.kind == "user"

    @property
    def is_service(self) -> bool:
        return self.kind == "service"

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def owns_house(self, house_id: str) -> bool:
        return house_id in self.house_ids

    def is_cloud_staff(self) -> bool:
        return self.role == "cloud_staff"


class JwksCache:
    """Fetches and caches the JWKS from C4."""

    def __init__(self, jwks_url: str, ttl_seconds: int = JWKS_CACHE_TTL_SECONDS):
        self.jwks_url = jwks_url
        self.ttl_seconds = ttl_seconds
        self._keys: dict[str, dict] = {}
        self._fetched_at: float = 0.0

    @classmethod
    def from_entries(cls, entries: list[dict]) -> JwksCache:
        """Build a cache pre-populated with JWKS entries (no HTTP fetch).

        C4 uses this in its own process so it verifies its own tokens without a
        circular HTTP call to itself.
        """
        cache = cls(jwks_url="local")
        cache._keys = {e["kid"]: e for e in entries if "kid" in e}
        cache._fetched_at = float("inf")
        return cache

    def _refresh(self) -> None:
        resp = httpx.get(self.jwks_url, timeout=5.0)
        resp.raise_for_status()
        payload = resp.json()
        keys = payload.get("keys", [])
        self._keys = {k["kid"]: k for k in keys if "kid" in k}
        self._fetched_at = time.time()

    def get(self, kid: str) -> dict:
        if not self._keys or (time.time() - self._fetched_at) > self.ttl_seconds:
            self._refresh()
        if kid not in self._keys:
            # Refetch once in case C4 rotated keys.
            self._refresh()
        if kid not in self._keys:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "unauthorized", "message": "unknown signing key"},
            )
        return self._keys[kid]


_default_cache: JwksCache | None = None


def configure_jwks(jwks_url: str) -> JwksCache:
    """Set the process-wide JWKS source. Call once at startup."""
    global _default_cache
    _default_cache = JwksCache(jwks_url)
    return _default_cache


def get_jwks_cache() -> JwksCache:
    if _default_cache is None:
        raise RuntimeError("JWKS not configured; call configure_jwks(jwks_url) at startup")
    return _default_cache


def verify_token(
    token: str,
    *,
    jwks: JwksCache | None = None,
    revoked_jtis: Iterable[str] | None = None,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    leeway: int = CLOCK_LEEWAY_SECONDS,
) -> Principal:
    """Verify a JWT and return the Principal.

    `revoked_jtis` is the set of revoked jti values the caller already knows
    about (C4 passes its own strict list; other services pass the cached
    `/auth/revoked` list). Unknown kids raise 401; expired tokens raise 401
    with code `token_expired`; revoked tokens raise 401 with code `token_revoked`.
    """
    jwks = jwks or get_jwks_cache()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "malformed token"},
        ) from exc

    kid = header.get("kid") if isinstance(header, dict) else None
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "missing kid"},
        )
    jwks_entry = jwks.get(kid)
    try:
        from jwt.algorithms import RSAAlgorithm

        signing_key = RSAAlgorithm.from_jwk(jwks_entry)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "bad signing key"},
        ) from exc

    try:
        claims = jwt.decode(
            token,
            key=signing_key,
            algorithms=["RS256"],
            issuer=issuer,
            audience=audience,
            leeway=leeway,
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "token_expired", "message": "token expired"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": str(exc)},
        ) from exc

    typ = claims.get("typ")
    jti = claims.get("jti")
    if typ == "user" and revoked_jtis is not None and jti in set(revoked_jtis):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "token_revoked", "message": "token revoked"},
        )

    if typ == "user":
        return Principal(
            kind="user",
            sub=str(claims["sub"]),
            role=claims.get("role"),
            tenant_id=claims.get("tenant_id"),
            house_ids=tuple(claims.get("house_ids", [])),
            jti=jti,
        )
    if typ == "service":
        return Principal(
            kind="service",
            sub=str(claims["sub"]),
            role=None,
            tenant_id=None,
            scopes=tuple(claims.get("scope", [])),
            jti=jti,
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "unauthorized", "message": f"unsupported typ {typ!r}"},
    )


def current_principal(
    authorization: str | None = Header(default=None),
) -> Principal:
    """FastAPI dependency: verify the Bearer token in the Authorization header."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "missing bearer token"},
        )
    token = authorization.split(" ", 1)[1].strip()
    return verify_token(token)


def require_roles(*roles: str) -> type:
    """Return a dependency that allows only the given user roles."""
    allowed = set(roles)

    def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.is_user or principal.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "forbidden", "message": "role not permitted"},
            )
        return principal

    return _dep


def require_scope(scope: str) -> type:
    """Return a dependency that allows only service tokens with the given scope."""

    def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.is_service or not principal.has_scope(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "forbidden", "message": f"scope {scope!r} required"},
            )
        return principal

    return _dep


def assert_house(
    principal: Principal, house_id: str, tenant_id_of_house: str | None = None
) -> None:
    """Raise 403 unless the principal may access this house.

    Cloud staff bypass. Owners must own the house. IoT staff must share the
    tenant. Service tokens are rejected (use require_scope at the route).
    """
    if principal.is_cloud_staff():
        return
    if principal.is_user and principal.role == "house_owner":
        if principal.owns_house(house_id):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden", "message": "not your house"},
        )
    if principal.is_user and principal.role == "iot_staff":
        if tenant_id_of_house and principal.tenant_id == tenant_id_of_house:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden", "message": "not your tenant"},
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "forbidden", "message": "house access denied"},
    )


def tenant_filter(principal: Principal) -> str | None:
    """Return the tenant_id a query should filter on for this principal.

    Cloud staff see all tenants (returns None unless the request names one).
    Other users are scoped to their own tenant_id.
    """
    if principal.is_cloud_staff():
        return None
    return principal.tenant_id
