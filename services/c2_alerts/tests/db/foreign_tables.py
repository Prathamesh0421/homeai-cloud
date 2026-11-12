"""The c4/c1 tables C2 reads (contract §4.5), built by C1's and C4's real migrations.

``migrate`` runs once per test session (``pg_engine``): it applies the revisions in
``services/c1_iot/alembic`` and ``services/c4_dashboard/alembic`` as their owners (``c1_app``,
``c4_app`` from ``infra/db/init.sql``), with each component's own version table, so the test
database has exactly the tables, constraints and ``c2_reader`` grants of the stack. Their
``env.py`` is not used (it imports that component's ``app`` package, which would clash with
C2's); the revision files themselves only use Alembic and SQLAlchemy.

``seed`` inserts the rows the gateway tests expect, inside the test's rolled-back transaction.
"""

from __future__ import annotations

from datetime import time
from pathlib import Path

from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from app.constants import SERVICE_CODES
from app.gateways.types import Contact, HouseSettings
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.factories import BATH, HOUSE_A1, KITCHEN, MAPLE, OAK, PINE, TENANT_A, TENANT_B, uid

SERVICES_DIR = Path(__file__).resolve().parents[3]
# (schema, owner role, Alembic directory); C4 first, as in the stack.
FOREIGN_MIGRATIONS = (
    ("c4", "c4_app", SERVICES_DIR / "c4_dashboard" / "alembic"),
    ("c1", "c1_app", SERVICES_DIR / "c1_iot" / "alembic"),
)

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
TENANTS = {TENANT_A: "Acme Care (test)", TENANT_B: "Sunrise Homes (test)"}


def migrate(engine: Engine) -> None:
    """Upgrade C4's and C1's schemas to their head revision (no-op when already there)."""
    for schema, owner, alembic_dir in FOREIGN_MIGRATIONS:
        cfg = Config()
        cfg.set_main_option("script_location", str(alembic_dir))
        script = ScriptDirectory.from_config(cfg)

        def upgrade(rev, _context, script=script):
            return script._upgrade_revs("head", rev)  # what `alembic upgrade head` runs

        with engine.begin() as conn:
            if conn.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": owner}
            ).first():
                conn.execute(text(f"SET LOCAL ROLE {owner}"))  # as compose and AWS migrate
            else:  # a database without infra/db/init.sql: migrate as the superuser
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
            with EnvironmentContext(cfg, script, fn=upgrade, destination_rev="head") as env:
                env.configure(connection=conn, version_table_schema=schema)
                with env.begin_transaction():
                    env.run_migrations()


def seed(session: Session) -> None:
    for tenant_id, name in TENANTS.items():  # c4.house_service_settings references c4.tenants
        session.execute(
            text("INSERT INTO c4.tenants (tenant_id, name, timezone) VALUES (:i, :n, 'UTC')"),
            {"i": tenant_id, "n": name},
        )
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
