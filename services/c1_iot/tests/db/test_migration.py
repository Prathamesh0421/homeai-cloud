"""Migration 0001: tables exist and reader roles get exactly the contract grants (02 §5.1).

``c2_reader`` may read only ``c1.houses`` and ``c1.rooms`` (C2's §4.5 queries); ``c3_reader`` and
``c4_reader`` read every c1 table. Checked with ``SET LOCAL ROLE`` inside the rolled-back
transaction, against the grants the real migration gave in ``pg_engine``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import ProgrammingError

from tests.db.conftest import _unavailable
from tests.factories import HOUSE_A1, ROOM_A1_BATH

TABLES = {"houses", "rooms", "camera_feeds", "feed_config_versions"}
INSUFFICIENT_PRIVILEGE = "42501"


def _require_roles(session, roles):
    found = set(
        session.execute(
            text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:r)"), {"r": list(roles)}
        ).scalars()
    )
    if missing := sorted(set(roles) - found):
        _unavailable(f"roles {missing} missing: run infra/db/init.sql on the test database")


def test_tables_exist(pg_engine):
    assert set(inspect(pg_engine).get_table_names(schema="c1")) >= TABLES


def test_partial_unique_indexes_exist(session):
    names = set(
        session.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'c1'")).scalars()
    )
    assert {"ux_houses_tenant_name", "ux_feeds_house_name", "ix_feeds_scope"} <= names


def test_c2_reader_reads_houses_and_rooms_with_contract_queries(seeded):
    _require_roles(seeded, ["c2_reader"])
    seeded.execute(text("SET LOCAL ROLE c2_reader"))
    house = seeded.execute(
        text(
            "SELECT house_id, tenant_id, name, timezone FROM c1.houses "
            "WHERE house_id = :h AND deleted_at IS NULL"
        ),
        {"h": HOUSE_A1},
    ).one()
    assert house.name == "Maple St"
    room = seeded.execute(
        text("SELECT room_id, name FROM c1.rooms WHERE room_id = :r"), {"r": ROOM_A1_BATH}
    ).one()
    assert room.name == "Bathroom"


@pytest.mark.parametrize("table", ["camera_feeds", "feed_config_versions"])
def test_c2_reader_cannot_read_other_c1_tables(seeded, table):
    _require_roles(seeded, ["c2_reader"])
    seeded.execute(text("SET LOCAL ROLE c2_reader"))
    with pytest.raises(ProgrammingError) as exc, seeded.begin_nested():
        seeded.execute(text(f"SELECT 1 FROM c1.{table}"))
    assert exc.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


def test_c2_reader_cannot_write_houses(seeded):
    _require_roles(seeded, ["c2_reader"])
    seeded.execute(text("SET LOCAL ROLE c2_reader"))
    with pytest.raises(ProgrammingError) as exc, seeded.begin_nested():
        seeded.execute(text("UPDATE c1.houses SET name = 'x'"))
    assert exc.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


@pytest.mark.parametrize("role", ["c3_reader", "c4_reader"])
def test_c3_and_c4_readers_read_every_c1_table(seeded, role):
    _require_roles(seeded, [role])
    seeded.execute(text(f"SET LOCAL ROLE {role}"))
    for table in sorted(TABLES):
        seeded.execute(text(f"SELECT count(*) FROM c1.{table}")).scalar()
