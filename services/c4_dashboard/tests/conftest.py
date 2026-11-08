"""Pytest fixtures for C4.

DB-backed tests need a reachable Postgres at DATABASE_URL_C4. When it is not
available those tests are skipped, so the pure-logic unit tests still run on a
fresh checkout without infra.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

# Make `homeai_common` importable without installing it.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "libs" / "homeai_common"))

from app.db.session import BASE_METADATA
from app.services.jwt_issuer import JwtIssuer, _pem_to_signing_key
from app.settings import Settings
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def _database_url() -> str | None:
    return os.environ.get("DATABASE_URL_C4")


def _has_postgres() -> bool:
    url = _database_url()
    if not url:
        return False
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


HAS_POSTGRES = _has_postgres()
skip_no_postgres = pytest.mark.skipif(not HAS_POSTGRES, reason="DATABASE_URL_C4 not reachable")


def _make_settings() -> Settings:
    key = _pem_to_signing_key(_test_private_pem(), "test-key")
    return Settings(
        env="test",
        jwt_private_key_pem=key.private_pem,
        jwt_kid="test-key",
        demo_mode=True,
    )


_TEST_PEM_CACHE: str | None = None


def _test_private_pem() -> str:
    global _TEST_PEM_CACHE
    if _TEST_PEM_CACHE is None:
        from app.services.jwt_issuer import generate_signing_key

        _TEST_PEM_CACHE = generate_signing_key("test-key").private_pem
    return _TEST_PEM_CACHE


@pytest.fixture
def settings() -> Settings:
    return _make_settings()


@pytest.fixture
def issuer(settings) -> JwtIssuer:
    key = _pem_to_signing_key(settings.jwt_private_key_pem, settings.jwt_kid)
    return JwtIssuer(settings=settings, key=key, previous=None)


@pytest.fixture
def db_engine():
    if not HAS_POSTGRES:
        pytest.skip("Postgres not available")
    engine = create_engine(_database_url(), pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS c4"))
        # Drop the users_public view (created by migrations) before
        # BASE_METADATA.drop_all, since the view depends on c4.users and is
        # not part of BASE_METADATA.
        conn.execute(text("DROP VIEW IF EXISTS c4.users_public"))
        conn.commit()
    BASE_METADATA.drop_all(engine, checkfirst=True)
    BASE_METADATA.create_all(engine, checkfirst=False)
    yield engine
    with engine.connect() as conn:
        conn.execute(text("DROP VIEW IF EXISTS c4.users_public"))
        conn.commit()
    BASE_METADATA.drop_all(engine, checkfirst=True)
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Iterator[Session]:
    import app.db.session as session_mod

    session_mod._engine = db_engine
    session_mod._SessionFactory = None
    factory = session_mod.get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(settings, issuer, db_engine, monkeypatch):
    """FastAPI TestClient with the test key and a fresh DB."""
    import app.deps as deps_mod
    import app.settings as settings_mod
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(deps_mod, "get_jwt_issuer", lambda: issuer)

    # Wire the JWKS cache used by homeai_common.auth to our test key directly.
    import homeai_common.auth as auth_mod

    class _StaticJwks(auth_mod.JwksCache):
        def __init__(self):
            super().__init__(jwks_url="static")
            self._keys = {"test-key": issuer.current.public_jwks_entry()}
            self._fetched_at = 1e12

        def _refresh(self):  # never hits the network
            pass

    auth_mod._default_cache = _StaticJwks()

    # Use the per-test engine for the DB dependency.
    import app.db.session as session_mod

    session_mod._engine = db_engine
    session_mod._SessionFactory = None

    def _get_db() -> Iterator[Session]:
        s = session_mod.get_session_factory()()
        try:
            yield s
        finally:
            s.close()

    from app.main import create_app

    app = create_app()
    app.dependency_overrides[deps_mod.get_jwt_issuer] = lambda: issuer
    from app.api.health import health as _health_router  # noqa: F401
    from app.db.session import get_db

    app.dependency_overrides[get_db] = _get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
