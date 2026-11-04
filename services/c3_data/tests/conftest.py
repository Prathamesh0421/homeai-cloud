"""Shared fixtures for C3 tests.

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
    for var in ("DATABASE_URL_C3", "C3_DATABASE_URL", "MONGO_URL_C3"):
        monkeypatch.delenv(var, raising=False)
    # Explicit kwargs beat the environment (CI exports DATABASE_URL_C3 etc.).
    return Settings(
        env="test",
        database_url="sqlite+pysqlite:///:memory:",
        database_reader_url=None,
        mongo_url=None,
        git_sha="test-sha",
        demo_mode=False,
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
