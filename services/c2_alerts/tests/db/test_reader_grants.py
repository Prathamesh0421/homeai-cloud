"""``c2_reader``'s Postgres privileges as ``infra/db/init.sql`` grants them (contract §4.5, §5.1).

The c4/c1 tables come from C4's and C1's real migrations, run as their owners (``c4_app``,
``c1_app``) with the grants those migrations give (``tests/db/foreign_tables.py``). The test
seeds them, then switches to ``c2_reader`` with ``SET LOCAL ROLE``, so every statement after that
is checked against that role's privileges. All inside the test's rolled-back transaction.
"""

from __future__ import annotations

import pytest
from app.gateways.c1_house_gateway import C1HouseGateway
from app.gateways.c4_settings_gateway import C4SettingsGateway
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from tests.db.conftest import _unavailable
from tests.db.foreign_tables import MAPLE_SETTINGS, seed
from tests.factories import BATH, HOUSE_A1, MAPLE, ROOM_A1_BATH

ROLES = ("c1_app", "c4_app", "c2_reader")
# The four tables C2 reads (§4.5), each with a column to use in an UPDATE.
READ_TABLES = {
    "c4.house_service_settings": "sensitivity",
    "c4.emergency_contacts": "name",
    "c1.houses": "name",
    "c1.rooms": "name",
}
INSUFFICIENT_PRIVILEGE = "42501"


def become(session: Session, role: str) -> None:
    session.execute(text("RESET ROLE"))
    session.execute(text(f"SET LOCAL ROLE {role}"))


def denied(session: Session, sql: str) -> None:
    with pytest.raises(ProgrammingError) as exc, session.begin_nested():
        session.execute(text(sql))
    assert exc.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE, exc.value.orig


@pytest.fixture
def owned(session) -> Session:
    """The §4.5 tables (created by their owners' migrations), seeded."""
    found = session.execute(
        text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:r)"), {"r": list(ROLES)}
    ).scalars()
    if missing := sorted(set(ROLES) - set(found)):
        _unavailable(f"roles {missing} missing: run infra/db/init.sql on the test database")
    seed(session)
    return session


@pytest.fixture
def reader(owned) -> Session:
    become(owned, "c2_reader")
    assert owned.execute(text("SELECT current_user")).scalar() == "c2_reader"
    return owned


def test_reader_runs_the_contract_queries(reader):
    settings, houses = C4SettingsGateway(reader), C1HouseGateway(reader)
    assert settings.settings(HOUSE_A1) == MAPLE_SETTINGS
    assert [c.priority for c in settings.contacts(HOUSE_A1)] == [1, 2, 3]
    assert settings.contact_houses() == [HOUSE_A1]
    assert houses.house(HOUSE_A1) == MAPLE
    assert houses.room(ROOM_A1_BATH) == BATH
    assert houses.houses([HOUSE_A1]) == {HOUSE_A1: MAPLE}
    assert houses.rooms([ROOM_A1_BATH]) == {ROOM_A1_BATH: BATH}


@pytest.mark.parametrize("table", READ_TABLES)
@pytest.mark.parametrize("verb", ["insert", "update", "delete", "truncate"])
def test_reader_cannot_write_what_it_reads(reader, table, verb):
    column = READ_TABLES[table]
    sql = {
        "insert": f"INSERT INTO {table} DEFAULT VALUES",
        "update": f"UPDATE {table} SET {column} = {column}",
        "delete": f"DELETE FROM {table}",
        "truncate": f"TRUNCATE {table}",
    }[verb]
    denied(reader, sql)


@pytest.mark.parametrize("schema", ["c1", "c4"])
def test_reader_cannot_create_tables(reader, schema):
    denied(reader, f"CREATE TABLE {schema}.c2_reader_probe (id int)")


@pytest.mark.parametrize(
    "sql", ["SELECT 1 FROM c2.alerts", "DELETE FROM c2.alert_rules", "SELECT 1 FROM c3.ml_models"]
)
def test_reader_has_no_access_to_other_schemas(reader, sql):
    # C2's own tables are written through c2_app; the reader connection never touches them.
    denied(reader, sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT password_hash FROM c4.users",
        "SELECT 1 FROM c4.tenants",
        "SELECT 1 FROM c4.service_clients",
        "SELECT 1 FROM c1.camera_feeds",
        "SELECT 1 FROM c1.feed_config_versions",
    ],
)
def test_reader_cannot_read_the_other_real_c1_c4_tables(reader, sql):
    # Only the four §4.5 tables are granted (C4 0002, C1 0001); the rest of c4/c1 is not.
    denied(reader, sql)


@pytest.mark.parametrize("owner", ["c1_app", "c4_app"])
def test_reader_cannot_read_other_c1_c4_tables(owned, owner):
    # A table the owner adds later (e.g. c4.users with password_hash) is not readable:
    # init.sql sets no default privileges for c2_reader on c1/c4.
    schema = owner.removesuffix("_app")
    become(owned, owner)
    owned.execute(text(f"CREATE TABLE {schema}.c2_reader_probe (secret text)"))
    become(owned, "c2_reader")
    denied(owned, f"SELECT secret FROM {schema}.c2_reader_probe")
