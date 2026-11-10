"""C1 playback URLs for the public alert view (C2-11, contract §4.4).

``GET /api/v1/clips/{media_id}/playback-url`` with C2's service token (scope ``clips:playback``)
answers a presigned URL that lives 15 minutes. The public alert view has no user token, so C2
asks with its own; logged-in pages call C1 from the browser with the user's token instead.

The view page refreshes every 30 s and must not hang or fail on C1: one short attempt (no
retries), any failure is "no clip" (``None``), a URL is reused until shortly before it expires
(so the player is not reset by a refresh), and a failure is remembered briefly so an outage does
not slow every refresh down. (Not ``homeai_common.service_client``: its token fetch has a fixed
5 s timeout and the HTTP client retries 502-504 for up to 14 s.)
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

SCOPE = "clips:playback"
TIMEOUT_S = 2.0
REUSE_MARGIN_S = 180.0  # stop handing out a URL 3 minutes before C1's expiry
FAILURE_TTL_S = 30.0  # how long "no clip" is remembered after a failure
TOKEN_REFRESH_RATIO = 0.8


class C1ClipClient:
    def __init__(
        self,
        *,
        c1_base_url: str,
        c4_base_url: str,
        client_id: str,
        client_secret: str,
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.c1_base_url = c1_base_url.rstrip("/")
        self.c4_base_url = c4_base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = http or httpx.Client(timeout=TIMEOUT_S)
        self.clock = clock
        self._lock = threading.Lock()
        self._token: tuple[str, float] | None = None  # (token, refresh after)
        self._urls: dict[str, tuple[str | None, float]] = {}  # media_id -> (url, reuse until)

    def playback_url(self, media_id: str) -> str | None:
        """The clip's presigned URL, or ``None`` when there is none or C1/C4 cannot say."""
        now = self.clock()
        with self._lock:
            cached = self._urls.get(media_id)
            if cached and cached[1] > now:
                return cached[0]
        url, reuse_until = self._fetch(media_id, now)
        with self._lock:
            self._urls = {k: v for k, v in self._urls.items() if v[1] > now}  # drop stale ones
            self._urls[media_id] = (url, reuse_until)
        return url

    def _fetch(self, media_id: str, now: float) -> tuple[str | None, float]:
        try:
            r = self.http.get(
                f"{self.c1_base_url}/api/v1/clips/{media_id}/playback-url",
                headers={"Authorization": f"Bearer {self._service_token(now)}"},
            )
            if r.status_code == 404:  # no such clip (e.g. a faked detection): not an error
                logger.debug("clip not in C1", extra={"media_id": media_id})
                return None, now + FAILURE_TTL_S
            r.raise_for_status()
            data = r.json()["data"]
            expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
            return data["url"], expires.timestamp() - REUSE_MARGIN_S
        except Exception as exc:  # C1 or C4 down, refused, slow or malformed: show no clip
            logger.warning(
                "clip playback URL unavailable",
                extra={"media_id": media_id, "error": f"{type(exc).__name__}: {exc}"[:200]},
            )
            return None, now + FAILURE_TTL_S

    def _service_token(self, now: float) -> str:
        with self._lock:
            if self._token and self._token[1] > now:
                return self._token[0]
        r = self.http.post(
            f"{self.c4_base_url}/api/v1/auth/service-token",
            json={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": [SCOPE],
            },
        )
        r.raise_for_status()
        data = r.json()["data"]
        token = data["token"]
        with self._lock:
            self._token = (token, now + int(data["expires_in"]) * TOKEN_REFRESH_RATIO)
        return token


def make_clip_client(settings) -> C1ClipClient | None:
    """``None`` without a service client secret (then the view shows no clip)."""
    if not settings.service_client_secret or not settings.service_client_id:
        return None
    return C1ClipClient(
        c1_base_url=settings.c1_base_url,
        c4_base_url=settings.c4_base_url,
        client_id=settings.service_client_id,
        client_secret=settings.service_client_secret,
    )
