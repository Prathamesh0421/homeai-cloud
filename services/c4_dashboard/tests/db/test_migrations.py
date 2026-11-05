"""The real Alembic migrations, run as c4_app (as compose and AWS do), and the reader grants
they leave (contract 02 §5.1). Needs Postgres with infra/db/init.sql applied (CI does this).
"""

from __future__ import annotations

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.conftest import skip_no_postgres
from tests.db.conftest import _alembic

pytestmark = skip_no_postgres

C2_READS = {"house_service_settings", "emergency_contacts"}
C3_READS = {
    "tenants",
    "users_public",
    "revoked_tokens",
    "house_service_settings",
    "emergency_contacts",
}


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
