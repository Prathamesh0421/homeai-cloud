"""JWT signing key from Secrets Manager: plain PEM (docs/03 §8, init-aws.sh) or rotation JSON."""

from __future__ import annotations

import json

import app.gateways.secrets_gateway as gw
from app.services.jwt_issuer import generate_signing_key
from app.settings import Settings


class _Client:
    class exceptions:
        class ResourceNotFoundException(Exception):
            pass

    def __init__(self, secret: str):
        self.secret = secret

    def get_secret_value(self, SecretId):
        return {"SecretString": self.secret}


def _load(monkeypatch, secret: str, **settings):
    monkeypatch.setattr(gw, "_client", lambda s: _Client(secret))
    return gw.load_signing_keys(Settings(jwt_private_key_pem=None, **settings))


def test_plain_pem_secret_uses_the_configured_kid(monkeypatch):
    pem = generate_signing_key("x").private_pem
    current, previous = _load(monkeypatch, pem + "\n", jwt_kid="2026-11")
    assert (current.kid, previous) == ("2026-11", None)
    assert current.private_pem.strip() == pem.strip()


def test_rotation_json_secret(monkeypatch):
    new, old = generate_signing_key("k2"), generate_signing_key("k1")
    secret = json.dumps(
        {
            "current": {"kid": "k2", "pem": new.private_pem},
            "previous": {"kid": "k1", "pem": old.private_pem},
        }
    )
    current, previous = _load(monkeypatch, secret)
    assert (current.kid, previous.kid) == ("k2", "k1")
