"""SignedLinkService (C2 plan §4.4): every row of the signed-link decision table."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from app.services.signed_link import ExpiredLink, InvalidLink, KeyRing, SignedLinkService

TRIGGERED = datetime(2026, 10, 24, 23, 10, tzinfo=UTC)
ALERT = "9b1e2f40-6c3d-4e1a-9f0b-2c8d1a7e5b07"
CONTACT = "3f2a7c10-0000-4000-8000-000000000001"
RING = KeyRing(current_kid="k2", keys={"k2": b"k" * 32, "k1": b"o" * 32})


def service(ring: KeyRing = RING) -> SignedLinkService:
    return SignedLinkService(keys=lambda: ring, public_base_url="https://homeai.example/")


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_round_trip():
    s = service()
    token = s.issue(ALERT, CONTACT, TRIGGERED)
    claims = s.verify(token, now=TRIGGERED + timedelta(hours=1))
    assert (claims.alert_id, claims.contact_id, claims.kid) == (ALERT, CONTACT, "k2")
    assert claims.expires_at == TRIGGERED + timedelta(hours=24)
    assert "=" not in token and token.count(".") == 1


def test_link_uses_public_base_url():
    s = service()
    token = s.issue(ALERT, CONTACT, TRIGGERED)
    assert s.link(token) == f"https://homeai.example/alert-view/{token}"


def test_payload_is_the_documented_json():
    payload = service().issue(ALERT, CONTACT, TRIGGERED).split(".")[0]
    padded = payload + "=" * (-len(payload) % 4)
    body = json.loads(base64.urlsafe_b64decode(padded))
    assert body == {
        "aid": ALERT,
        "cid": CONTACT,
        "exp": int((TRIGGERED + timedelta(hours=24)).timestamp()),
        "kid": "k2",
    }


def test_valid_until_the_last_second_then_expired():
    s = service()
    token = s.issue(ALERT, CONTACT, TRIGGERED)
    assert s.verify(token, now=TRIGGERED + timedelta(hours=24)).alert_id == ALERT
    with pytest.raises(ExpiredLink):
        s.verify(token, now=TRIGGERED + timedelta(hours=24, seconds=1))


def test_old_key_still_verifies_after_rotation():
    old = SignedLinkService(keys=lambda: KeyRing("k1", {"k1": b"o" * 32}), public_base_url="x")
    token = old.issue(ALERT, CONTACT, TRIGGERED)
    assert service().verify(token, now=TRIGGERED).kid == "k1"


def _tamper_payload(token: str) -> str:
    payload, sig = token.split(".")
    body = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    body["aid"] = "00000000-0000-4000-8000-000000000000"
    return f"{b64(json.dumps(body).encode())}.{sig}"


def _extend_expiry(token: str) -> str:
    payload, sig = token.split(".")
    body = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    body["exp"] += 86400
    return f"{b64(json.dumps(body).encode())}.{sig}"


@pytest.mark.parametrize(
    "mangle",
    [
        lambda t: t.replace(".", ""),  # no separator
        lambda t: t + ".extra",  # too many parts
        lambda t: "!!!." + t.split(".")[1],  # payload is not base64
        lambda t: b64(b"not json") + "." + t.split(".")[1],
        lambda t: b64(b"[1, 2]") + "." + t.split(".")[1],  # JSON but not an object
        lambda t: t.split(".")[0] + "." + t.split(".")[1][:-2] + "AA",  # signature changed
        lambda t: t.split(".")[0] + ".",  # empty signature
        _tamper_payload,  # alert id changed, old signature
        _extend_expiry,  # expiry pushed out, old signature
        lambda t: "",
        lambda t: b64(b'{"kid": ["k2"]}') + "." + t.split(".")[1],  # unhashable kid
    ],
)
def test_tampered_or_malformed_tokens_are_invalid(mangle):
    s = service()
    with pytest.raises(InvalidLink):
        s.verify(mangle(s.issue(ALERT, CONTACT, TRIGGERED)), now=TRIGGERED)


def test_unknown_kid_is_invalid():
    token = SignedLinkService(
        keys=lambda: KeyRing("k9", {"k9": b"z" * 32}), public_base_url="x"
    ).issue(ALERT, CONTACT, TRIGGERED)
    with pytest.raises(InvalidLink):
        service().verify(token, now=TRIGGERED)


@pytest.mark.parametrize(
    "body",
    [
        {"aid": ALERT, "cid": CONTACT, "kid": "k2"},  # no exp
        {"aid": ALERT, "cid": CONTACT, "exp": "tomorrow", "kid": "k2"},
        {"aid": 7, "cid": CONTACT, "exp": 1, "kid": "k2"},
        {"aid": ALERT, "cid": CONTACT, "exp": 1},  # no kid
        {"aid": ALERT, "cid": CONTACT, "exp": 10**20, "kid": "k2"},  # exp out of range
    ],
)
def test_signed_but_incomplete_payloads_are_invalid(body):
    import hashlib
    import hmac

    payload = b64(json.dumps(body).encode())
    sig = b64(hmac.new(b"k" * 32, payload.encode(), hashlib.sha256).digest())
    with pytest.raises(InvalidLink):
        service().verify(f"{payload}.{sig}", now=TRIGGERED)


def test_issue_needs_an_aware_time():
    with pytest.raises(ValueError):
        service().issue(ALERT, CONTACT, datetime(2026, 10, 24, 23, 10))
