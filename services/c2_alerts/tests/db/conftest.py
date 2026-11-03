"""Postgres-backed fixtures: migrate once per session, roll back after every test.

Needs ``DATABASE_URL_C2``. Locally the tests skip without it; on CI (``CI=true``) a missing
or unreachable database is a failure, so coverage never comes from silently skipped tests.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

SERVICE_DIR = Path(__file__).resolve().parents[2]
# STANDIN(P0-5): tests connect as the Postgres superuser. Once infra/db/init.sql creates the
# c2_app / c2_reader roles, add tests that c2_reader can read only its contract §4.5 tables.
# Read now, before any test's monkeypatch can remove it.
DATABASE_URL = os.environ.get("DATABASE_URL_C2")


def _unavailable(reason: str) -> None:
    if os.environ.get("CI") == "true":
        pytest.fail(f"Postgres required on CI: {reason}", pytrace=False)
    pytest.skip(reason)


@pytest.fixture(scope="session")
def pg_engine() -> Iterator[Engine]:
    if not DATABASE_URL:
        _unavailable("DATABASE_URL_C2 not set")
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        _unavailable(f"Postgres unreachable: {exc}")

    # Fresh c2 schema from the real migrations (so tests also cover 0001/0002).
    cfg = Config(str(SERVICE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_DIR / "alembic"))
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS c2 CASCADE"))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def session(pg_engine) -> Iterator[Session]:
    """A session inside an outer transaction that is rolled back after the test."""
    conn = pg_engine.connect()
    outer = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield s
    finally:
        s.close()
        outer.rollback()
        conn.close()
