"""Test helpers: mint RSA keys and tokens without a live C4.

Other services use these in their pytest suites before C4 is running, so they
can verify tokens through `homeai_common.auth` against a fake JWKS.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .auth import AUDIENCE, ISSUER


def make_test_keys(*, kid: str = "test-key", bits: int = 2048) -> tuple[str, str, dict]:
    """Generate an RSA keypair. Returns (private_pem, public_pem, jwks_entry)."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public = private.public_key()
    public_pem = public.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    numbers = public.public_numbers()
    import base64

    def _b64(num: int) -> str:
        return (
            base64.urlsafe_b64encode(num.to_bytes((num.bit_length() + 7) // 8, "big"))
            .rstrip(b"=")
            .decode()
        )

    jwks_entry = {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _b64(numbers.n),
        "e": _b64(numbers.e),
    }
    return private_pem, public_pem, jwks_entry


def mint_user_token(
    private_pem: str,
    *,
    kid: str = "test-key",
    user_id: str | None = None,
    role: str = "house_owner",
    tenant_id: str | None = None,
    house_ids: list[str] | None = None,
    email: str = "tester@homeai.test",
    ttl_seconds: int = 3600,
    jti: str | None = None,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "typ": "user",
        "sub": user_id or str(uuid.uuid4()),
        "role": role,
        "tenant_id": tenant_id or str(uuid.uuid4()),
        "house_ids": house_ids or [],
        "email": email,
        "jti": jti or str(uuid.uuid4()),
        "iat": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": kid})


def mint_service_token(
    private_pem: str,
    *,
    kid: str = "test-key",
    client_id: str = "c3-worker",
    scopes: list[str] | None = None,
    ttl_seconds: int = 900,
    jti: str | None = None,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "typ": "service",
        "sub": client_id,
        "scope": scopes or [],
        "jti": jti or str(uuid.uuid4()),
        "iat": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": kid})
