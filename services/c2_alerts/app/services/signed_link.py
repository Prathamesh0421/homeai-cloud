"""Signed 24-hour alert-view links for emergency contacts (C2 plan §4.4).

token = ``base64url(json{aid, cid, exp, kid}) + "." + base64url(HMAC-SHA256(key[kid], payload))``
with ``exp = triggered_at + 24h`` (epoch seconds). No login is needed to open the link, so the
token alone must prove which alert it is for; tampering with any byte invalidates it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

LINK_TTL = timedelta(hours=24)


class InvalidLink(Exception):
    """Malformed, tampered, or signed with an unknown key (-> 404)."""


class ExpiredLink(Exception):
    """Genuine but past ``exp`` (-> 401 token_expired)."""


@dataclass(frozen=True)
class KeyRing:
    current_kid: str
    keys: dict[str, bytes]  # kid -> raw HMAC key; previous keys keep old links valid


@dataclass(frozen=True)
class LinkClaims:
    alert_id: str
    contact_id: str
    expires_at: datetime
    kid: str


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    if not text:
        raise InvalidLink("empty segment")
    try:
        # Strict: characters outside the URL-safe alphabet are an error, not silently dropped.
        return base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidLink("bad base64") from exc


def _sign(key: bytes, payload: str) -> bytes:
    return hmac.new(key, payload.encode("ascii"), hashlib.sha256).digest()


@dataclass
class SignedLinkService:
    keys: Callable[[], KeyRing]
    public_base_url: str

    def issue(self, alert_id: str, contact_id: str, triggered_at: datetime) -> str:
        if triggered_at.tzinfo is None:
            raise ValueError("triggered_at must be timezone-aware")
        ring = self.keys()
        body = {
            "aid": alert_id,
            "cid": contact_id,
            "exp": int((triggered_at + LINK_TTL).timestamp()),
            "kid": ring.current_kid,
        }
        payload = _b64encode(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
        return f"{payload}.{_b64encode(_sign(ring.keys[ring.current_kid], payload))}"

    def link(self, token: str) -> str:
        return f"{self.public_base_url.rstrip('/')}/alert-view/{token}"

    def verify(self, token: str, now: datetime) -> LinkClaims:
        """Check in the documented order: shape, decode, key, signature, then expiry."""
        parts = token.split(".")
        if len(parts) != 2:
            raise InvalidLink("expected payload.signature")
        payload, signature = parts
        try:
            body = json.loads(_b64decode(payload))
        except (ValueError, UnicodeDecodeError) as exc:
            raise InvalidLink("payload is not JSON") from exc
        if not isinstance(body, dict):
            raise InvalidLink("payload is not an object")

        kid = body.get("kid")
        key = self.keys().keys.get(kid) if isinstance(kid, str) else None
        if key is None:
            raise InvalidLink("unknown key id")
        if not hmac.compare_digest(_sign(key, payload), _b64decode(signature)):
            raise InvalidLink("bad signature")

        aid, cid, exp = (body.get(k) for k in ("aid", "cid", "exp"))
        if not (isinstance(aid, str) and isinstance(cid, str) and isinstance(exp, int)):
            raise InvalidLink("incomplete payload")
        try:
            expires_at = datetime.fromtimestamp(exp, UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise InvalidLink("exp out of range") from exc
        if now > expires_at:
            raise ExpiredLink
        return LinkClaims(alert_id=aid, contact_id=cid, expires_at=expires_at, kid=kid)
