"""The c4/c1 tables C2 reads (contract §4.5), created inside a test's rolled-back transaction.

Real columns (C4 migration 0001, C1 plan §2.1) minus foreign keys to tables C2 never reads.
With ``as_owners=True`` the tables are created as ``c4_app`` / ``c1_app`` and get the grants
the owning migrations give ``c2_reader`` (C4 migration 0002; C1's migration), as in the stack.
"""

from __future__ import annotations

from datetime import time

from app.constants import SERVICE_CODES
from app.gateways.types import Contact, HouseSettings
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.factories import BATH, HOUSE_A1, KITCHEN, MAPLE, OAK, PINE, TENANT_A, uid

# STANDIN(C1-02): c1/c4 tables copied from C4 migration 0001 and the C1 plan §2.1. Once C1's
# migration exists, build them by running the real C1 and C4 migrations and delete this DDL.
SCHEMAS = "CREATE SCHEMA IF NOT EXISTS c4; CREATE SCHEMA IF NOT EXISTS c1;"
C4_DDL = """
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
"""
C1_DDL = """
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

# The only grants c2_reader gets on c1/c4 (contract 02 §5.1); init.sql grants schema USAGE.
C4_GRANTS = "GRANT SELECT ON c4.house_service_settings, c4.emergency_contacts TO c2_reader;"
C1_GRANTS = "GRANT SELECT ON c1.houses, c1.rooms TO c2_reader;"

HOUSE_DELETED = "22222222-0000-0000-0000-0000000000dd"
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


def create_tables(session: Session, *, as_owners: bool = False) -> None:
    if not as_owners:
        session.execute(text(SCHEMAS))  # init.sql creates them in the real stack
    for owner, ddl, grants in (("c4_app", C4_DDL, C4_GRANTS), ("c1_app", C1_DDL, C1_GRANTS)):
        if as_owners:
            session.execute(text(f"SET LOCAL ROLE {owner}"))
        session.execute(text(ddl))
        if as_owners:
            session.execute(text(grants))
    if as_owners:
        session.execute(text("RESET ROLE"))


def seed(session: Session, *, as_owners: bool = False) -> None:
    create_tables(session, as_owners=as_owners)
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
