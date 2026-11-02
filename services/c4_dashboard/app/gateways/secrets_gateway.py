"""Secrets Manager access for the JWT signing key.

In local dev the key can be supplied directly via `C4_JWT_PRIVATE_KEY_PEM`
(or generated on first run when `DEMO_MODE=1`). On AWS the key is fetched from
Secrets Manager secret `homeai/jwt-signing-key` (JSON `{"current":..., "previous":...?}`).
"""

from __future__ import annotations

import json
from typing import Any

import boto3

from app.services.jwt_issuer import SigningKey, _pem_to_signing_key, generate_signing_key
from app.settings import Settings


def _client(settings: Settings):
    kwargs = {"region_name": settings.aws_region}
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return boto3.client("secretsmanager", **kwargs)


def load_signing_keys(settings: Settings) -> tuple[SigningKey, SigningKey | None]:
    """Return (current, previous|None). Generates and stores a key when none exists in dev."""
    if settings.jwt_private_key_pem:
        current = _pem_to_signing_key(settings.jwt_private_key_pem, settings.jwt_kid)
        return current, None

    client = _client(settings)
    secret_id = settings.jwt_private_key_secret
    try:
        response = client.get_secret_value(SecretId=secret_id)
        payload: dict[str, Any] = json.loads(response["SecretString"])
    except client.exceptions.ResourceNotFoundException:  # type: ignore[attr-defined]
        if not settings.demo_mode:
            raise
        current = generate_signing_key(settings.jwt_kid)
        client.create_secret(
            Name=secret_id,
            SecretString=json.dumps({"current": {"kid": current.kid, "pem": current.private_pem}}),
        )
        return current, None
    except Exception:
        # LocalStack not running and no PEM set: fall back to an in-memory key
        # only in demo mode (so tests and `make web` work without infra).
        if settings.demo_mode:
            return generate_signing_key(settings.jwt_kid), None
        raise

    current = _pem_to_signing_key(payload["current"]["pem"], payload["current"]["kid"])
    previous = None
    if payload.get("previous"):
        previous = _pem_to_signing_key(payload["previous"]["pem"], payload["previous"]["kid"])
    return current, previous
