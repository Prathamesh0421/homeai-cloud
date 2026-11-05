"""DB fixtures shared by the migration and seed tests: the real migrations run as c4_app."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.db.session import BASE_METADATA
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import Engine

from tests.conftest import _database_url

SERVICE_DIR = Path(__file__).resolve().parents[2]


def owner_url() -> str:
    """The test database as c4_app (the role compose and AWS migrate and run as)."""
    url = make_url(_database_url()).set(username="c4_app", password="devpass")
    return url.render_as_string(hide_password=False)


def _alembic() -> Config:
    # No ini file: env.py would otherwise reconfigure logging for the rest of the test run.
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_DIR / "alembic"))
    return cfg


@pytest.fixture
def admin() -> Iterator[Engine]:
    engine = create_engine(_database_url(), isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        roles = set(
            conn.execute(
                text(
                    "SELECT rolname FROM pg_roles WHERE rolname IN ('c4_app','c2_reader','c3_reader')"
                )
            ).scalars()
        )
    if roles != {"c4_app", "c2_reader", "c3_reader"}:
        pytest.skip("roles missing: run infra/db/init.sql on the test database")
    yield engine
    engine.dispose()


@pytest.fixture
def migrated(admin, monkeypatch) -> Iterator[Engine]:
    """c4 at head, migrated by c4_app; back to base afterwards."""

    def clean() -> None:
        with admin.connect() as conn:
            conn.execute(text("DROP VIEW IF EXISTS c4.users_public"))
            conn.execute(text("DROP TABLE IF EXISTS c4.alembic_version"))
            conn.execute(text("DROP TABLE IF EXISTS c4.grant_probe"))
        BASE_METADATA.drop_all(admin, checkfirst=True)  # left by the ORM-built DB tests

    clean()
    # What an earlier init.sql did: every table c4_app creates is readable by both readers.
    with admin.connect() as conn:
        conn.execute(
            text(
                "ALTER DEFAULT PRIVILEGES FOR ROLE c4_app IN SCHEMA c4 "
                "GRANT SELECT ON TABLES TO c2_reader, c3_reader"
            )
        )
    monkeypatch.setenv("DATABASE_URL_C4", owner_url())
    command.upgrade(_alembic(), "head")
    yield admin
    command.downgrade(_alembic(), "base")
    clean()
