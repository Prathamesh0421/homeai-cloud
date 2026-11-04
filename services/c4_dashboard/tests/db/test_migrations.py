"""The real Alembic migrations, run as c4_app (as compose and AWS do), and the reader grants
they leave (contract 02 §5.1). Needs Postgres with infra/db/init.sql applied (CI does this).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.db.session import BASE_METADATA
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import Engine

from tests.conftest import _database_url, skip_no_postgres

pytestmark = skip_no_postgres

SERVICE_DIR = Path(__file__).resolve().parents[2]
C2_READS = {"house_service_settings", "emergency_contacts"}
C3_READS = {
    "tenants",
    "users_public",
    "revoked_tokens",
    "house_service_settings",
    "emergency_contacts",
}


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
    as_owner = make_url(_database_url()).set(username="c4_app", password="devpass")
    monkeypatch.setenv("DATABASE_URL_C4", as_owner.render_as_string(hide_password=False))
    command.upgrade(_alembic(), "head")
    yield admin
    command.downgrade(_alembic(), "base")
    clean()


def _readable(engine: Engine, role: str) -> set[str]:
    with engine.connect() as conn:
        return set(
            conn.execute(
                text(
                    "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'c4' AND c.relkind IN ('r', 'v') "
                    "AND has_table_privilege(:role, c.oid, 'SELECT')"
                ),
                {"role": role},
            ).scalars()
        )


def _can(engine: Engine, sql: str) -> bool:
    with engine.connect() as conn:
        return bool(conn.execute(text(sql)).scalar())


def test_migrations_run_as_the_owner_role(migrated):
    with migrated.connect() as conn:
        owners = set(
            conn.execute(text("SELECT tableowner FROM pg_tables WHERE schemaname = 'c4'")).scalars()
        )
    assert owners == {"c4_app"}


def test_c2_reader_reads_only_settings_and_contacts(migrated):
    assert _readable(migrated, "c2_reader") == C2_READS
    assert not _can(migrated, "SELECT has_table_privilege('c2_reader', 'c4.users', 'SELECT')")


def test_c3_reader_never_sees_password_or_secret_hashes(migrated):
    assert _readable(migrated, "c3_reader") == C3_READS
    assert not _can(
        migrated, "SELECT has_column_privilege('c3_reader', 'c4.users', 'password_hash', 'SELECT')"
    )
    assert not _can(
        migrated,
        "SELECT has_column_privilege('c3_reader', 'c4.service_clients', 'secret_hash', 'SELECT')",
    )
    assert _can(
        migrated,
        "SELECT has_column_privilege('c3_reader', 'c4.service_clients', 'client_id', 'SELECT')",
    )


@pytest.mark.parametrize("role", ["c2_reader", "c3_reader"])
def test_readers_cannot_write(migrated, role):
    for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
        assert not _can(
            migrated,
            f"SELECT has_table_privilege('{role}', 'c4.emergency_contacts', '{privilege}')",
        )


def test_tables_added_later_are_not_readable_by_default(migrated):
    with migrated.connect() as conn:
        conn.execute(text("SET ROLE c4_app"))
        conn.execute(text("CREATE TABLE c4.grant_probe (secret text)"))
        conn.execute(text("RESET ROLE"))
    for role in ("c2_reader", "c3_reader"):
        assert "grant_probe" not in _readable(migrated, role)


def test_downgrade_removes_the_grants(migrated):
    command.downgrade(_alembic(), "0001")
    assert _readable(migrated, "c2_reader") == set()
    command.upgrade(_alembic(), "head")
