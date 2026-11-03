"""Shared fixtures for C2 tests.

Unit and API tests here need no infrastructure: the app's health checks are injected.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

# Make homeai_common importable on a fresh checkout without installing it.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "libs" / "homeai_common"))

from app.main import create_app
from app.settings import Settings
from fastapi.testclient import TestClient


@pytest.fixture
def settings(monkeypatch) -> Settings:
    for var in ("DATABASE_URL_C2", "C2_DATABASE_URL", "MONGO_URL_C2_READER"):
        monkeypatch.delenv(var, raising=False)
    # Explicit kwargs beat the environment (CI exports DATABASE_READER_URL_C2 etc.).
    return Settings(
        env="test",
        database_url="sqlite+pysqlite:///:memory:",
        database_reader_url=None,
        mongo_reader_url=None,
        git_sha="test-sha",
    )


@pytest.fixture
def make_client(settings) -> Iterator[Callable[..., TestClient]]:
    """Build a TestClient with injected health checks (default: all healthy)."""
    clients: list[TestClient] = []

    def _make(checks: dict | None = None) -> TestClient:
        app = create_app(settings, checks=checks if checks is not None else {"db": lambda: None})
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def auth_header(monkeypatch):
    """``auth_header(role=..., ...)`` -> Authorization header verified by a static test JWKS.

    Call it after the TestClient has started (app startup configures the real JWKS URL).
    """
    from homeai_common import auth
    from homeai_common.auth import JwksCache
    from homeai_common.testing import make_test_keys, mint_service_token, mint_user_token

    private, _public, entry = make_test_keys(kid="test-key")

    class _StaticJwks(JwksCache):
        def __init__(self):
            super().__init__(jwks_url="static")
            self._keys = {entry["kid"]: entry}
            self._fetched_at = 1e12

        def _refresh(self) -> None:  # never hits the network
            pass

    def _header(*, service_scopes: list[str] | None = None, **claims) -> dict[str, str]:
        monkeypatch.setattr(auth, "_default_cache", _StaticJwks())
        if service_scopes is not None:
            token = mint_service_token(private, kid="test-key", scopes=service_scopes)
        else:
            token = mint_user_token(private, kid="test-key", **claims)
        return {"Authorization": f"Bearer {token}"}

    return _header
