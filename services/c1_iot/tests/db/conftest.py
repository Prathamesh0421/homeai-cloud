"""Postgres-backed fixtures: migrate once per session, roll back after every test.

Needs ``DATABASE_URL_C1``. Locally the tests skip without it; on CI (``CI=true``) a missing or
unreachable database is a failure, so coverage never comes from silently skipped tests.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.api.deps import (
    get_detections,
    get_media_repo,
    get_media_repo_optional,
    get_session,
    get_storage,
)
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.factories import (
    HOUSE_A1,
    HOUSE_A2,
    HOUSE_B1,
    OWNER_USER,
    ROOM_A1_BATH,
    ROOM_A1_KITCHEN,
    ROOM_B1_KITCHEN,
    STAFF_USER,
    TENANT_A,
    TENANT_B,
    make_house,
    make_room,
)
from tests.fakes import FakeDetections, FakeMediaRepo, FakeStorage

SERVICE_DIR = Path(__file__).resolve().parents[2]
# Tests connect as the Postgres superuser (to drop and rebuild schema c1); the reader grants
# from the migration are checked with SET ROLE in test_reader_grants.py.
# Read now, before any test's monkeypatch can remove it.
DATABASE_URL = os.environ.get("DATABASE_URL_C1")


def _unavailable(reason: str) -> None:
    if os.environ.get("CI") == "true":
        pytest.fail(f"Postgres required on CI: {reason}", pytrace=False)
    pytest.skip(reason)


def alembic_config() -> Config:
    cfg = Config(str(SERVICE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_DIR / "alembic"))
    return cfg


@pytest.fixture(scope="session")
def pg_engine() -> Iterator[Engine]:
    if not DATABASE_URL:
        _unavailable("DATABASE_URL_C1 not set")
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        _unavailable(f"Postgres unreachable: {exc}")

    # Fresh c1 tables from the real migration (so tests also cover 0001 and its grants). The
    # schema itself stays: init.sql gave it its owner and the readers' USAGE grants.
    cfg = alembic_config()
    with engine.begin() as conn:
        conn.execute(
            text(
                "DROP TABLE IF EXISTS c1.feed_config_versions, c1.camera_feeds, c1.rooms, "
                "c1.houses, c1.alembic_version CASCADE"
            )
        )
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


@pytest.fixture
def seeded(session) -> Session:
    """Maple and Oak (tenant A) and Pine (tenant B), with two Maple rooms and one Pine room."""
    session.add_all(
        [
            make_house(HOUSE_A1, TENANT_A, name="Maple St"),
            make_house(HOUSE_A2, TENANT_A, name="Oak Ave"),
            make_house(HOUSE_B1, TENANT_B, name="Pine Rd", timezone="America/New_York"),
        ]
    )
    session.flush()
    session.add_all(
        [
            make_room(HOUSE_A1, ROOM_A1_KITCHEN, name="Kitchen", room_type="kitchen"),
            make_room(HOUSE_A1, ROOM_A1_BATH, name="Bathroom", room_type="bathroom"),
            make_room(HOUSE_B1, ROOM_B1_KITCHEN, name="Kitchen", room_type="kitchen"),
        ]
    )
    session.flush()
    return session


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def media() -> FakeMediaRepo:
    return FakeMediaRepo()


@pytest.fixture
def detections() -> FakeDetections:
    return FakeDetections([])


@pytest.fixture
def api(settings, seeded, storage, media, detections) -> Iterator[TestClient]:
    """TestClient whose requests share the test's rolled-back session; S3 and Mongo are fakes."""
    app = create_app(settings, checks={})
    app.dependency_overrides[get_session] = lambda: seeded
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_media_repo] = lambda: media
    app.dependency_overrides[get_media_repo_optional] = lambda: media
    app.dependency_overrides[get_detections] = lambda: detections
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def staff(api, auth_header) -> dict[str, str]:
    """iot_staff of tenant A."""
    return auth_header(user_id=STAFF_USER, role="iot_staff", tenant_id=TENANT_A)


@pytest.fixture
def ops(api, auth_header) -> dict[str, str]:
    """cloud_staff (every tenant)."""
    return auth_header(role="cloud_staff")


@pytest.fixture
def owner(api, auth_header) -> dict[str, str]:
    """Owner of Maple only."""
    return auth_header(
        user_id=OWNER_USER, role="house_owner", tenant_id=TENANT_A, house_ids=[HOUSE_A1]
    )


@pytest.fixture
def staff_b(api, auth_header) -> dict[str, str]:
    """iot_staff of tenant B (isolation checks)."""
    return auth_header(role="iot_staff", tenant_id=TENANT_B)
