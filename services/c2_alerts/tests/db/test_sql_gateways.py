"""C4 settings/contacts and C1 house/room readers against Postgres, and the fakes against the
same expectations. The c4/c1 tables come from ``tests/db/foreign_tables.py``.
"""

from __future__ import annotations

import pytest
from app.constants import SERVICE_CODES
from app.gateways.c1_house_gateway import C1HouseGateway
from app.gateways.c4_settings_gateway import C4SettingsGateway
from app.gateways.types import DependencyUnavailableError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tests.db.foreign_tables import CONTACTS, HOUSE_DELETED, MAPLE_SETTINGS, seed
from tests.factories import (
    BATH,
    HOUSE_A1,
    HOUSE_A2,
    HOUSE_B1,
    KITCHEN,
    MAPLE,
    OAK,
    PINE,
    ROOM_A1_BATH,
    ROOM_A1_KITCHEN,
    uid,
)
from tests.fakes import FakeHouseReader, FakeSettingsReader


@pytest.fixture(params=["sql", "fake"])
def readers(request, session):
    """(SettingsReader, HouseReader) — real gateways over Postgres, or the fakes."""
    if request.param == "sql":
        seed(session)
        return C4SettingsGateway(session), C1HouseGateway(session)
    return (
        FakeSettingsReader([MAPLE_SETTINGS], {HOUSE_A1: CONTACTS}),
        FakeHouseReader([MAPLE, OAK, PINE], [BATH, KITCHEN]),
    )


# --- shared expectations (both implementations) ---------------------------------------------


def test_settings_row(readers):
    settings, _ = readers
    assert settings.settings(HOUSE_A1) == MAPLE_SETTINGS
    assert settings.settings(HOUSE_A1).has_quiet_hours


def test_missing_settings_row_gives_contract_defaults(readers):
    settings, _ = readers
    got = settings.settings(HOUSE_A2)
    assert got.is_default
    assert got.enabled_services == frozenset(SERVICE_CODES)
    assert (got.quiet_start, got.quiet_end, got.sensitivity) == (None, None, "medium")
    assert not got.has_quiet_hours


def test_contacts_in_priority_order(readers):
    settings, _ = readers
    assert [c.name for c in settings.contacts(HOUSE_A1)] == [
        "Daughter Dana",
        "Carer Cam",
        "Neighbor Ned",
    ]
    assert settings.contacts(HOUSE_A2) == []


def test_house_lookup_hides_deleted_and_unknown(readers):
    _, houses = readers
    assert houses.house(HOUSE_A1) == MAPLE
    assert houses.house(HOUSE_DELETED) is None
    assert houses.house(uid()) is None


def test_room_lookup(readers):
    _, houses = readers
    assert houses.room(ROOM_A1_BATH) == BATH
    assert houses.room(uid()) is None


def test_batch_lookups(readers):
    _, houses = readers
    got = houses.houses([HOUSE_A1, HOUSE_B1, HOUSE_A1, HOUSE_DELETED, uid()])
    assert got == {HOUSE_A1: MAPLE, HOUSE_B1: PINE}
    assert houses.rooms([ROOM_A1_BATH, None, ROOM_A1_KITCHEN, uid()]) == {
        ROOM_A1_BATH: BATH,
        ROOM_A1_KITCHEN: KITCHEN,
    }
    assert houses.houses([]) == {}
    assert houses.rooms([None]) == {}


# --- SQL only: outages ----------------------------------------------------------------------


def test_component_not_deployed_is_dependency_unavailable(session):
    # No c1/c4 tables in this transaction: "relation does not exist".
    with pytest.raises(DependencyUnavailableError) as exc:
        C1HouseGateway(session).house(HOUSE_A1)
    assert exc.value.source == "c1"
    with pytest.raises(DependencyUnavailableError, match="c4"):
        C4SettingsGateway(session).contacts(HOUSE_A1)
    # The reader session was rolled back and still works.
    assert session.execute(text("SELECT 1")).scalar() == 1


def test_database_down_is_dependency_unavailable():
    engine = create_engine(
        "postgresql+psycopg://u:p@127.0.0.1:1/homeai", connect_args={"connect_timeout": 1}
    )
    with Session(engine) as session, pytest.raises(DependencyUnavailableError, match="c4"):
        C4SettingsGateway(session).settings(HOUSE_A1)
    engine.dispose()


def test_fakes_can_simulate_outages():
    settings, houses = FakeSettingsReader(), FakeHouseReader()
    settings.down = houses.down = True
    with pytest.raises(DependencyUnavailableError):
        settings.settings(HOUSE_A1)
    with pytest.raises(DependencyUnavailableError):
        houses.rooms([ROOM_A1_BATH])
