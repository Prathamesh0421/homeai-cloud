"""Shared FastAPI dependencies for C4."""

from __future__ import annotations

from fastapi import Depends

from app.services.jwt_issuer import JwtIssuer
from app.settings import Settings, get_settings

_issuer_cache: dict[str, JwtIssuer] = {}


def get_jwt_issuer(settings: Settings = Depends(get_settings)) -> JwtIssuer:
    # Cache one issuer per jwt_kid; settings are not hashable so we can't lru_cache.
    key = settings.jwt_kid
    if key not in _issuer_cache:
        from app.gateways.secrets_gateway import load_signing_keys

        current, previous = load_signing_keys(settings)
        _issuer_cache[key] = JwtIssuer(settings=settings, key=current, previous=previous)
    return _issuer_cache[key]


def reset_issuer_cache() -> None:
    """Test hook: clear the cached issuer so a new key takes effect."""
    _issuer_cache.clear()
