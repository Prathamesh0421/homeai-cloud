"""RS256 JWT issuer for C4 (user and service tokens).

Keys come from `secrets_gateway` (Secrets Manager / LocalStack) or, for local
dev and tests, from `C4_JWT_PRIVATE_KEY_PEM` directly. JWKS is published from
the same key material.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from app.settings import Settings

ISSUER = "homeai-c4"
AUDIENCE = "homeai"


@dataclass
class SigningKey:
    kid: str
    private_pem: str
    public_numbers: tuple[int, int]  # (n, e)

    def public_jwks_entry(self) -> dict:
        import base64

        def _b64(num: int) -> str:
            return (
                base64.urlsafe_b64encode(num.to_bytes((num.bit_length() + 7) // 8, "big"))
                .rstrip(b"=")
                .decode()
            )

        n, e = self.public_numbers
        return {
            "kty": "RSA",
            "kid": self.kid,
            "use": "sig",
            "alg": "RS256",
            "n": _b64(n),
            "e": _b64(e),
        }


def _pem_to_signing_key(pem: str, kid: str) -> SigningKey:
    private = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(private, RSAPrivateKey):
        raise ValueError("JWT signing key must be RSA")
    public = private.public_key().public_numbers()
    return SigningKey(kid=kid, private_pem=pem, public_numbers=(public.n, public.e))


def generate_signing_key(kid: str, bits: int = 2048) -> SigningKey:
    private = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return _pem_to_signing_key(pem, kid)


class JwtIssuer:
    """Holds the current (and optionally previous) signing key."""

    def __init__(self, settings: Settings, key: SigningKey, previous: SigningKey | None = None):
        self.settings = settings
        self.current = key
        self.previous = previous

    def jwks(self) -> dict:
        keys = [self.current.public_jwks_entry()]
        if self.previous is not None:
            keys.append(self.previous.public_jwks_entry())
        return {"keys": keys}

    def issue_user_token(
        self,
        *,
        user_id: str,
        role: str,
        tenant_id: str,
        house_ids: list[str],
        email: str,
    ) -> tuple[str, str, int]:
        now = int(time.time())
        ttl = self.settings.jwt_user_ttl_seconds
        jti = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "typ": "user",
            "sub": user_id,
            "role": role,
            "tenant_id": tenant_id,
            "house_ids": list(house_ids),
            "email": email,
            "jti": jti,
            "iat": now,
            "exp": now + ttl,
        }
        token = jwt.encode(
            payload, self.current.private_pem, algorithm="RS256", headers={"kid": self.current.kid}
        )
        return token, jti, ttl

    def issue_service_token(self, *, client_id: str, scopes: list[str]) -> tuple[str, str, int]:
        now = int(time.time())
        ttl = self.settings.jwt_service_ttl_seconds
        jti = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "typ": "service",
            "sub": client_id,
            "scope": list(scopes),
            "jti": jti,
            "iat": now,
            "exp": now + ttl,
        }
        token = jwt.encode(
            payload, self.current.private_pem, algorithm="RS256", headers={"kid": self.current.kid}
        )
        return token, jti, ttl


def landing_for_role(role: str) -> str:
    return {
        "house_owner": "/home/overview",
        "iot_staff": "/iot/feeds",
        "cloud_staff": "/ops/dashboard",
    }.get(role, "/login")
