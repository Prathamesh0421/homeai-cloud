"""C4's own service token for upstream stats calls (contracts §2.3, §4.6).

The dashboard reads C1/C2/C3 stats as client ``c4-dashboard`` (scopes ``feeds:read``,
``alerts:read``, ``records:read``), not with the viewer's user token: C1 ``/feeds/stats``
does not accept house owners, and C2/C3 do not accept ``iot_staff``. The aggregator narrows
every call to the viewer's tenant/houses itself, so the wider service scope never leaks
other tenants' numbers.

C4 is the issuer, so the token is minted in process through the same path as
``POST /auth/service-token`` (client secret checked against ``c4.service_clients``),
cached, and refreshed at 80% of its TTL.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from app.errors import ApiError
from app.settings import Settings

STATS_SCOPES: tuple[str, ...] = ("feeds:read", "alerts:read", "records:read")
DEFAULT_CLIENT_ID = "c4-dashboard"

# (client_id, client_secret, scopes) -> (token, expires_in seconds)
Minter = Callable[[str, str, list[str]], tuple[str, int]]


def _mint_via_db(client_id: str, client_secret: str, scopes: list[str]) -> tuple[str, int]:
    from app.db.session import session_scope
    from app.deps import get_jwt_issuer
    from app.services import auth_service
    from app.settings import get_settings

    issuer = get_jwt_issuer(get_settings())
    with session_scope() as session:
        result = auth_service.issue_service_token(
            session,
            issuer=issuer,
            client_id=client_id,
            client_secret=client_secret,
            requested_scopes=scopes,
        )
    return result["token"], int(result["expires_in"])


class StatsTokenProvider:
    """Caches the ``c4-dashboard`` service token; thread-safe (the aggregator fans out)."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str | None,
        scopes: tuple[str, ...] = STATS_SCOPES,
        minter: Minter = _mint_via_db,
        clock: Callable[[], float] = time.monotonic,
        refresh_at_ratio: float = 0.8,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = list(scopes)
        self._minter = minter
        self._clock = clock
        self._ratio = refresh_at_ratio
        self._lock = threading.Lock()
        self._token: str | None = None
        self._refresh_after = 0.0

    def token(self) -> str:
        with self._lock:
            if self._token is None or self._clock() >= self._refresh_after:
                if not self.client_secret:
                    raise ApiError(
                        503,
                        "service_token_unavailable",
                        "SERVICE_CLIENT_SECRET_C4 is not set; cannot read upstream stats",
                    )
                token, ttl = self._minter(self.client_id, self.client_secret, self.scopes)
                self._token = token
                self._refresh_after = self._clock() + int(ttl * self._ratio)
            return self._token

    def invalidate(self) -> None:
        with self._lock:
            self._token = None


_provider: StatsTokenProvider | None = None
_provider_lock = threading.Lock()


def get_stats_token_provider(settings: Settings) -> StatsTokenProvider:
    """Process-wide provider (one token shared by all requests)."""
    global _provider
    with _provider_lock:
        if _provider is None:
            _provider = StatsTokenProvider(
                client_id=settings.service_client_id or DEFAULT_CLIENT_ID,
                client_secret=settings.service_client_secret,
            )
        return _provider


def reset_stats_token_provider() -> None:
    """Test hook."""
    global _provider
    with _provider_lock:
        _provider = None
