"""JWT verification shared by every service.

Implements contracts §2.4 of docs/02_CONTRACTS.md:
  1. Fetch JWKS (cache 10 min, refetch on unknown kid).
  2. Verify RS256 signature, iss=homeai-c4, aud=homeai, exp (60s leeway).
  3. For typ=user: reject if jti is revoked (C4 exposes GET /auth/revoked; cache list 60 s).
  4. Build a Principal and pass it to handlers.

This module is intentionally framework-light: it exposes the verification
function and a FastAPI dependency. C4 imports it from the same package; other
services install `homeai-common` as a path dependency.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, status

ISSUER = "homeai-c4"
AUDIENCE = "homeai"
CLOCK_LEEWAY_SECONDS = 60
JWKS_CACHE_TTL_SECONDS = 600
REVOCATION_CACHE_TTL_SECONDS = 60

logger = logging.getLogger(__name__)

# Shared .env lists every service-client secret; pick the first present so C1-C3
# can poll /auth/revoked without a per-service code change (configure_jwks wires this).
_SERVICE_CLIENT_CANDIDATES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("c2-alerts", "SERVICE_CLIENT_SECRET_C2", "dev-c2-secret", ("clips:playback",)),
    ("c3-worker", "SERVICE_CLIENT_SECRET_C3", "dev-c3-secret", ("alerts:evaluate",)),
    ("c3-data", "SERVICE_CLIENT_SECRET_C3", "dev-c3-secret", ("alerts:evaluate",)),
    ("c4-dashboard", "SERVICE_CLIENT_SECRET_C4", "dev-c4-secret", ("feeds:read",)),
    ("device-uploader", "SERVICE_CLIENT_SECRET_DEVICE", "dev-device-secret", ("ingest:write",)),
)


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


class RevocationCache:
    """Fetches and caches ``GET /auth/revoked`` from C4 (contracts §2.4 / §4.7).

    TTL defaults to 60 s. After logout, other services reject the jti within one
    cache window. Failures keep the last successful list (fail-open) so a brief
    C4 blip does not 401 every user request.
    """

    def __init__(
        self,
        revoked_url: str,
        token_provider: Callable[[], str],
        ttl_seconds: int = REVOCATION_CACHE_TTL_SECONDS,
    ):
        self.revoked_url = revoked_url
        self.token_provider = token_provider
        self.ttl_seconds = ttl_seconds
        self._jtis: set[str] = set()
        self._fetched_at: float = 0.0
        self._ever_fetched = False

    def invalidate(self) -> None:
        """Drop the TTL so the next ``get()`` refetches (tests / forced refresh)."""
        self._fetched_at = 0.0

    def get(self) -> set[str]:
        if (not self._ever_fetched) or (time.time() - self._fetched_at) > self.ttl_seconds:
            self._refresh()
        return set(self._jtis)

    def _refresh(self) -> None:
        try:
            token = self.token_provider()
            since = datetime.fromtimestamp(0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            resp = httpx.get(
                self.revoked_url,
                headers={"Authorization": f"Bearer {token}"},
                params={"since": since},
                timeout=5.0,
            )
            resp.raise_for_status()
            self._jtis = _parse_revoked_payload(resp.json())
            self._fetched_at = time.time()
            self._ever_fetched = True
        except Exception:
            logger.warning("revocation list refresh failed; using last known list", exc_info=True)
            # Keep previous _jtis; still advance the clock so we do not hammer C4.
            self._fetched_at = time.time()
            self._ever_fetched = True


def _parse_revoked_payload(payload: object) -> set[str]:
    """Accept the implemented ``{"data":{"jti":[...]}}`` and the contracts array form."""
    if not isinstance(payload, dict):
        return set()
    data = payload.get("data")
    if isinstance(data, list):
        return {str(j) for j in data}
    if isinstance(data, dict):
        jtis = data.get("jti", [])
        if isinstance(jtis, list):
            return {str(j) for j in jtis}
    return set()


def _c4_base_from_jwks(jwks_url: str) -> str | None:
    marker = "/.well-known/jwks.json"
    if jwks_url.endswith(marker):
        return jwks_url[: -len(marker)]
    return None


def _secret_for(env_var: str, default: str) -> str | None:
    if env_var in os.environ:
        return os.environ[env_var] or None
    # Local/dev compose shares .env defaults; prod must set the env vars explicitly.
    if os.environ.get("ENV", "local") == "local":
        return default
    return None


def _credentials_from_env(
    *,
    service_client_id: str | None = None,
    service_client_secret: str | None = None,
    service_scopes: Sequence[str] | None = None,
) -> tuple[str, str, list[str]] | None:
    if service_client_id and service_client_secret:
        return service_client_id, service_client_secret, list(service_scopes or [])

    preferred = (
        service_client_id
        or os.environ.get("SERVICE_CLIENT_ID")
        or os.environ.get("C2_SERVICE_CLIENT_ID")
        or os.environ.get("C3_SERVICE_CLIENT_ID")
        or os.environ.get("C4_SERVICE_CLIENT_ID")
    )
    by_id = {c[0]: c for c in _SERVICE_CLIENT_CANDIDATES}
    if preferred and preferred in by_id:
        client_id, env_var, default, scopes = by_id[preferred]
        secret = service_client_secret or _secret_for(env_var, default)
        if secret:
            return client_id, secret, list(service_scopes or scopes)

    # Shared .env is mounted into every container; any seeded client can poll /auth/revoked
    # (service scope any). Used when this process has no own client (e.g. c1-iot).
    for client_id, env_var, default, scopes in _SERVICE_CLIENT_CANDIDATES:
        secret = _secret_for(env_var, default)
        if secret:
            return client_id, secret, list(scopes)
    return None


_default_cache: JwksCache | None = None
_default_revocation_cache: RevocationCache | None = None


def configure_jwks(
    jwks_url: str,
    *,
    c4_base_url: str | None = None,
    service_client_id: str | None = None,
    service_client_secret: str | None = None,
    service_scopes: Sequence[str] | None = None,
    revoked_ttl_seconds: int | None = None,
) -> JwksCache:
    """Set the process-wide JWKS source. Call once at startup.

    When C4 base URL and a service client can be resolved (explicit args or the
    shared ``.env``), also wires a 60 s revocation cache so ``current_principal``
    rejects logged-out JTIs. C4 itself uses ``JwksCache.from_entries`` and skips
    this HTTP path.
    """
    global _default_cache
    _default_cache = JwksCache(jwks_url)
    if jwks_url != "local":
        _maybe_configure_revocation(
            jwks_url,
            c4_base_url=c4_base_url,
            service_client_id=service_client_id,
            service_client_secret=service_client_secret,
            service_scopes=service_scopes,
            revoked_ttl_seconds=revoked_ttl_seconds,
        )
    return _default_cache


def configure_revocation(
    revoked_url: str,
    token_provider: Callable[[], str],
    *,
    ttl_seconds: int = REVOCATION_CACHE_TTL_SECONDS,
) -> RevocationCache:
    """Set the process-wide revocation list cache (explicit; used by tests)."""
    global _default_revocation_cache
    _default_revocation_cache = RevocationCache(
        revoked_url, token_provider, ttl_seconds=ttl_seconds
    )
    return _default_revocation_cache


def _maybe_configure_revocation(
    jwks_url: str,
    *,
    c4_base_url: str | None = None,
    service_client_id: str | None = None,
    service_client_secret: str | None = None,
    service_scopes: Sequence[str] | None = None,
    revoked_ttl_seconds: int | None = None,
) -> RevocationCache | None:
    base = (
        c4_base_url or os.environ.get("C4_BASE_URL") or _c4_base_from_jwks(jwks_url) or ""
    ).rstrip("/")
    creds = _credentials_from_env(
        service_client_id=service_client_id,
        service_client_secret=service_client_secret,
        service_scopes=service_scopes,
    )
    if not base or creds is None:
        return None

    client_id, secret, scopes = creds
    from homeai_common.service_client import ServiceTokenProvider

    provider = ServiceTokenProvider(
        c4_base_url=base,
        client_id=client_id,
        client_secret=secret,
        scopes=scopes,
    )
    ttl = revoked_ttl_seconds
    if ttl is None:
        raw = os.environ.get("REVOCATION_CACHE_TTL_SECONDS")
        ttl = int(raw) if raw else REVOCATION_CACHE_TTL_SECONDS
    return configure_revocation(
        f"{base}/api/v1/auth/revoked",
        provider.token,
        ttl_seconds=ttl,
    )


def get_jwks_cache() -> JwksCache:
    if _default_cache is None:
        raise RuntimeError("JWKS not configured; call configure_jwks(jwks_url) at startup")
    return _default_cache


def get_revocation_cache() -> RevocationCache | None:
    return _default_revocation_cache


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
    `/auth/revoked` list). When omitted and a process-wide ``RevocationCache``
    is configured, that cache is used. Unknown kids raise 401; expired tokens
    raise 401 with code `token_expired`; revoked tokens raise 401 with code
    `token_revoked`.
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
    effective_revoked = revoked_jtis
    if effective_revoked is None and _default_revocation_cache is not None:
        effective_revoked = _default_revocation_cache.get()
    if typ == "user" and effective_revoked is not None and jti in set(effective_revoked):
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
