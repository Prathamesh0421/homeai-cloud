"""HMAC key for alert-view links, from Secrets Manager ``homeai/alert-view-hmac`` (cached 5 min).

Secret formats accepted:
* plain base64 of the key (docs/03 §8: "32 random bytes, base64"), used as kid ``k1``;
* JSON ``{"current": {"kid": "k2", "key": "<b64>"}, "previous": {"kid": "k1", "key": "<b64>"}}``
  to rotate keys without breaking links already sent.
``C2_ALERT_VIEW_KEY`` (base64) overrides Secrets Manager for local runs.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import time
from collections.abc import Callable
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.gateways.types import DependencyUnavailableError
from app.services.signed_link import KeyRing

logger = logging.getLogger(__name__)

CACHE_TTL_S = 300
MIN_KEY_BYTES = 16


class InvalidKeyMaterial(ValueError):
    pass


def _decode_key(text: str) -> bytes:
    try:
        raw = base64.b64decode(text.strip() + "=" * (-len(text.strip()) % 4), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidKeyMaterial("alert-view key is not base64") from exc
    if len(raw) < MIN_KEY_BYTES:
        raise InvalidKeyMaterial(f"alert-view key must be at least {MIN_KEY_BYTES} bytes")
    return raw


def parse_secret(secret: str) -> KeyRing:
    text = secret.strip()
    if text.startswith("{"):
        body = json.loads(text)
        current = body["current"]
        keys = {current["kid"]: _decode_key(current["key"])}
        previous = body.get("previous")
        if previous:
            keys[previous["kid"]] = _decode_key(previous["key"])
        return KeyRing(current_kid=current["kid"], keys=keys)
    return KeyRing(current_kid="k1", keys={"k1": _decode_key(text)})


class AlertViewKeyProvider:
    """Callable returning the current KeyRing; refetches at most every ``ttl_s`` seconds."""

    def __init__(
        self,
        *,
        secret_id: str,
        region: str,
        endpoint_url: str | None = None,
        override_b64: str | None = None,
        demo_mode: bool = False,
        client: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        ttl_s: float = CACHE_TTL_S,
    ) -> None:
        self.secret_id = secret_id
        self.region = region
        self.endpoint_url = endpoint_url or None
        self.demo_mode = demo_mode
        self.clock = clock
        self.ttl_s = ttl_s
        self._client = client
        self._override = parse_secret(override_b64) if override_b64 else None
        self._ring: KeyRing | None = None
        self._fetched_at = 0.0
        self._ephemeral: KeyRing | None = None

    def _sm(self) -> Any:
        if self._client is None:
            self._client = boto3.client(
                "secretsmanager", region_name=self.region, endpoint_url=self.endpoint_url
            )
        return self._client

    def _demo_key(self, why: str) -> KeyRing:
        if self._ephemeral is None:
            logger.warning(
                "alert-view key unavailable, using an in-memory key (DEMO_MODE); links stop "
                "working when the process restarts",
                extra={"secret_id": self.secret_id, "reason": why},
            )
            self._ephemeral = KeyRing("ephemeral", {"ephemeral": os.urandom(32)})
        return self._ephemeral

    def __call__(self) -> KeyRing:
        if self._override is not None:
            return self._override
        now = self.clock()
        if self._ring is not None and now - self._fetched_at < self.ttl_s:
            return self._ring
        try:
            secret = self._sm().get_secret_value(SecretId=self.secret_id)["SecretString"]
            self._ring = parse_secret(secret)
            self._fetched_at = now
            return self._ring
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "ClientError")
            return self._fallback(code)
        except (BotoCoreError, InvalidKeyMaterial, KeyError, ValueError) as exc:
            return self._fallback(type(exc).__name__)

    def _fallback(self, why: str) -> KeyRing:
        if self._ring is not None:  # Secrets Manager blip: keep the last good keys
            logger.warning(
                "alert-view key refresh failed, keeping cached keys", extra={"reason": why}
            )
            return self._ring
        if self.demo_mode:
            return self._demo_key(why)
        raise DependencyUnavailableError("secrets", why)
