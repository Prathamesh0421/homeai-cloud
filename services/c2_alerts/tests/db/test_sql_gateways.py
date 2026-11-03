"""C4 settings/contacts and C1 house/room readers against Postgres, and the fakes against the
same expectations.

The c4/c1 tables are created inside each test's rolled-back transaction with the real
columns (C4 migration 0001, C1 plan §2.1) minus foreign keys to tables C2 never reads.
"""

from __future__ import annotations

from datetime import time

import pytest
from app.constants import SERVICE_CODES
from app.gateways.c1_house_gateway import C1HouseGateway
from app.gateways.c4_settings_gateway import C4SettingsGateway
from app.gateways.types import Contact, DependencyUnavailableError, House, HouseSettings, Room
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tests.factories import (
    HOUSE_A1,
    HOUSE_A2,
    HOUSE_B1,
    ROOM_A1_BATH,
    ROOM_A1_KITCHEN,
    TENANT_A,
    TENANT_B,
    uid,
)
from tests.fakes import FakeHouseReader, FakeSettingsReader

DDL = """
CREATE SCHEMA IF NOT EXISTS c4;
CREATE SCHEMA IF NOT EXISTS c1;
CREATE TABLE c4.house_service_settings (
  house_id UUID PRIMARY KEY, tenant_id UUID NOT NULL, enabled_services TEXT[] NOT NULL,
  quiet_start TIME, quiet_end TIME, sensitivity VARCHAR(6) NOT NULL DEFAULT 'medium',
  updated_by UUID NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK ((quiet_start IS NULL) = (quiet_end IS NULL)));
CREATE TABLE c4.emergency_contacts (
  contact_id UUID PRIMARY KEY, house_id UUID NOT NULL, tenant_id UUID NOT NULL,
  name VARCHAR(80) NOT NULL, email VARCHAR(254) NOT NULL, phone VARCHAR(20),
  contact_type VARCHAR(20) NOT NULL, priority SMALLINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (house_id, email), UNIQUE (house_id, priority));
CREATE TABLE c1.houses (
  house_id UUID PRIMARY KEY, tenant_id UUID NOT NULL, name VARCHAR(80) NOT NULL,
  address VARCHAR(200), timezone VARCHAR(40) NOT NULL, owner_user_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ);
CREATE TABLE c1.rooms (
  room_id UUID PRIMARY KEY, house_id UUID NOT NULL REFERENCES c1.houses(house_id),
  name VARCHAR(60) NOT NULL, room_type VARCHAR(12) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (house_id, name));
"""

HOUSE_DELETED = "22222222-0000-0000-0000-0000000000dd"
MAPLE = House(HOUSE_A1, TENANT_A, "Maple St", "America/Los_Angeles")
OAK = House(HOUSE_A2, TENANT_A, "Oak Ave", "America/Los_Angeles")
PINE = House(HOUSE_B1, TENANT_B, "Pine Rd", "America/New_York")
BATH = Room(ROOM_A1_BATH, HOUSE_A1, "Bathroom")
KITCHEN = Room(ROOM_A1_KITCHEN, HOUSE_A1, "Kitchen")
MAPLE_SETTINGS = HouseSettings(
    house_id=HOUSE_A1,
    tenant_id=TENANT_A,
    enabled_services=frozenset(set(SERVICE_CODES) - {"wellness"}),
    quiet_start=time(22, 0),
    quiet_end=time(7, 0),
    sensitivity="high",
)
CONTACTS = [  # inserted out of order on purpose
    Contact(uid(), "Neighbor Ned", "ned@example.com", "neighbor", 3),
    Contact(uid(), "Daughter Dana", "dana@example.com", "family", 1),
    Contact(uid(), "Carer Cam", "cam@example.com", "caregiver", 2),
]


def _seed(session: Session) -> None:
    session.execute(text(DDL))
    for house in (MAPLE, OAK, PINE):
        session.execute(
            text(
                "INSERT INTO c1.houses (house_id, tenant_id, name, timezone) VALUES (:i,:t,:n,:z)"
            ),
            {"i": house.house_id, "t": house.tenant_id, "n": house.name, "z": house.timezone},
        )
    session.execute(
        text(
            "INSERT INTO c1.houses (house_id, tenant_id, name, timezone, deleted_at) "
            "VALUES (:i, :t, 'Gone Ln', 'UTC', now())"
        ),
        {"i": HOUSE_DELETED, "t": TENANT_A},
    )
    for room in (BATH, KITCHEN):
        session.execute(
            text(
                "INSERT INTO c1.rooms (room_id, house_id, name, room_type) VALUES (:i,:h,:n,'other')"
            ),
            {"i": room.room_id, "h": room.house_id, "n": room.name},
        )
    s = MAPLE_SETTINGS
    session.execute(
        text(
            "INSERT INTO c4.house_service_settings (house_id, tenant_id, enabled_services, "
            "quiet_start, quiet_end, sensitivity, updated_by) "
            "VALUES (:h, :t, :svc, :qs, :qe, :sens, :t)"
        ),
        {
            "h": s.house_id,
            "t": s.tenant_id,
            "svc": sorted(s.enabled_services),
            "qs": s.quiet_start,
            "qe": s.quiet_end,
            "sens": s.sensitivity,
        },
    )
    for c in CONTACTS:
        session.execute(
            text(
                "INSERT INTO c4.emergency_contacts (contact_id, house_id, tenant_id, name, email, "
                "contact_type, priority) VALUES (:id, :h, :t, :n, :e, :ct, :p)"
            ),
            {
                "id": c.contact_id,
                "h": HOUSE_A1,
                "t": TENANT_A,
                "n": c.name,
                "e": c.email,
                "ct": c.contact_type,
                "p": c.priority,
            },
        )


@pytest.fixture(params=["sql", "fake"])
def readers(request, session):
    """(SettingsReader, HouseReader) — real gateways over Postgres, or the fakes."""
    if request.param == "sql":
        _seed(session)
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
