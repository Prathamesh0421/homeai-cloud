"""Service-to-service HTTP client with automatic service-token refresh.

C4 itself does not need this (it issues the tokens), but other services use it
to call C1/C2/C3. It is part of the auth slice because it is the consumer side
of `POST /auth/service-token`.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import httpx


class ServiceTokenProvider:
    """Calls C4 `/auth/service-token`, caches the token, refreshes at 80% of TTL."""

    def __init__(
        self,
        *,
        c4_base_url: str,
        client_id: str,
        client_secret: str,
        scopes: Sequence[str],
        refresh_at_ratio: float = 0.8,
    ):
        self.c4_base_url = c4_base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = list(scopes)
        self.refresh_at_ratio = refresh_at_ratio
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._refresh_after: float = 0.0

    def _fetch(self) -> None:
        resp = httpx.post(
            f"{self.c4_base_url}/api/v1/auth/service-token",
            json={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": self.scopes,
            },
            timeout=5.0,
        )
        resp.raise_for_status()
        body = resp.json()["data"]
        self._token = body["token"]
        ttl = int(body["expires_in"])
        self._expires_at = time.time() + ttl
        self._refresh_after = time.time() + int(ttl * self.refresh_at_ratio)

    def token(self) -> str:
        if self._token is None or time.time() >= self._refresh_after:
            self._fetch()
        return self._token  # type: ignore[return-value]


class ServiceHttpClient:
    """httpx wrapper that adds the service bearer token and retries 502/503/504."""

    def __init__(
        self,
        *,
        base_url: str,
        token_provider: ServiceTokenProvider,
        timeout: float = 5.0,
        backoff: Sequence[float] = (2.0, 4.0, 8.0),
    ):
        self.base_url = base_url.rstrip("/")
        self.token_provider = token_provider
        self.timeout = timeout
        self.backoff = tuple(backoff)

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Exception | None = None
        for attempt in range(len(self.backoff) + 1):
            headers = kwargs.pop("headers", {}) or {}
            headers["Authorization"] = f"Bearer {self.token_provider.token()}"
            try:
                resp = httpx.request(method, url, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < len(self.backoff):
                    time.sleep(self.backoff[attempt])
                    continue
                raise
            if resp.status_code in (502, 503, 504) and attempt < len(self.backoff):
                time.sleep(self.backoff[attempt])
                continue
            return resp
        if last_exc:
            raise last_exc
        raise RuntimeError("unreachable")

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)
