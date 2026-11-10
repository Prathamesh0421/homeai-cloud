"""C3-10 (Tier 2/3): cross-component schema assumptions and fail-closed behavior.

- Review item 1: rooms scope through their house so the tenant still applies (needs stand-in
  c1.houses / c1.rooms, which this test creates and drops; C1 has not shipped).
- Review item 5: a missing grant (42501) is re-raised, not swallowed as "C1 absent".
- Audit 4.1: an information_schema column contract for the scope columns the code assumes.

Role model: these tests need to act as the c1 owner (create c1 tables) and as c3_reader (read
them). Rather than depend on per-role passwords (which differ between the compose stack and CI),
we open one connection from DATABASE_URL_C3 and ``SET ROLE`` to switch. On CI that DSN is the
superuser, so SET ROLE works; locally it is c3_app, which may not be a member of c1_app, so the
role switch is refused and the test skips (never silently passes).
"""

from __future__ import annotations

import contextlib
import os
import uuid

import pytest
from app.services.record_query import SCOPE_COLUMNS, RecordQuery, _safe_c1_query
from app.services.record_scope import RecordScope
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

pytestmark = pytest.mark.integration


def _require(reason: str):
    if os.environ.get("CI") == "true":
        pytest.fail(f"integration store required on CI: {reason}", pytrace=False)
    pytest.skip(reason)


def _engine():
    pg = os.environ.get("DATABASE_URL_C3")
    if not pg:
        _require("DATABASE_URL_C3 not set")
    return create_engine(pg, future=True)


@contextlib.contextmanager
def _role(conn, role: str):
    """SET ROLE for the duration of the block; skip the test if the switch is refused."""
    try:
        conn.execute(text(f"SET ROLE {role}"))
    except ProgrammingError as exc:
        pytest.skip(f"cannot SET ROLE {role} on this connection: {type(exc.orig).__name__}")
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            conn.execute(text("RESET ROLE"))


# -- review item 1: rooms scoped through house ---------------------------------------------
def test_rooms_scoped_through_house_by_tenant():
    """Rooms have no tenant_id; the scope must reach them through their house (Rev4 §11).

    C1 has shipped (``c1.houses``/``c1.rooms`` are real tables now), so this seeds rows into the
    real tables rather than fabricating stand-ins. It keys everything to unique UUIDs and a
    unique room name per house, and cleans up by DELETE-ing only its own rows — it never drops
    C1's tables (dropping them would break C1's ``camera_feeds`` FK). Skips if C1 is absent.
    """
    eng = _engine()
    acme, sunrise = str(uuid.uuid4()), str(uuid.uuid4())
    maple, pine = str(uuid.uuid4()), str(uuid.uuid4())
    kitchen, bedroom = str(uuid.uuid4()), str(uuid.uuid4())
    # Unique room names so the (house_id, name) unique constraint never collides with seed data.
    tag = uuid.uuid4().hex[:8]
    try:
        with eng.connect() as conn:
            exists = conn.execute(
                text(
                    "SELECT to_regclass('c1.rooms') IS NOT NULL AND "
                    "to_regclass('c1.houses') IS NOT NULL"
                )
            ).scalar_one()
            if not exists:
                pytest.skip("c1.houses/c1.rooms not in this DB (c1 not migrated here)")

        with eng.begin() as conn:
            # Seed C1's real tables on the plain connection. We do not SET ROLE here: the owner of
            # the c1 tables (the superuser in the compose/CI DB, c1_app on RDS) can write, and the
            # seed role is just plumbing — the scope assertion below is what runs as c3_reader. If
            # the DSN role cannot write c1 (a non-owner local DSN), skip rather than fail.
            try:
                conn.execute(
                    text(
                        "INSERT INTO c1.houses (house_id, tenant_id, name, timezone) VALUES "
                        "(:h1,:t1,:n1,'UTC'), (:h2,:t2,:n2,'UTC')"
                    ),
                    {
                        "h1": maple,
                        "t1": acme,
                        "n1": f"Maple-{tag}",
                        "h2": pine,
                        "t2": sunrise,
                        "n2": f"Pine-{tag}",
                    },
                )
                conn.execute(
                    text(
                        "INSERT INTO c1.rooms (room_id, house_id, name, room_type) VALUES "
                        "(:r1,:h1,:rn1,'kitchen'), (:r2,:h2,:rn2,'bedroom')"
                    ),
                    {
                        "r1": kitchen,
                        "h1": maple,
                        "rn1": f"Kitchen-{tag}",
                        "r2": bedroom,
                        "h2": pine,
                        "rn2": f"Bedroom-{tag}",
                    },
                )
            except ProgrammingError as exc:
                pytest.skip(f"cannot seed c1 tables with this DSN role: {type(exc.orig).__name__}")

            # Read as c3_reader (the role the Records API uses); c3_reader already has SELECT on
            # c1.* from C1's migration / init.sql.
            with _role(conn, "c3_reader"):
                q = RecordQuery(conn, None)
                rows, total = q.list(
                    "rooms",
                    RecordScope(tenant_id=acme),
                    house_id=None,
                    from_=None,
                    to=None,
                    filters={},
                    offset=0,
                    limit=25,
                )
                assert total == 1
                assert rows[0]["name"] == f"Kitchen-{tag}"

                rows, total = q.list(
                    "rooms",
                    RecordScope(tenant_id=sunrise),
                    house_id=None,
                    from_=None,
                    to=None,
                    filters={},
                    offset=0,
                    limit=25,
                )
                assert total == 1
                assert rows[0]["name"] == f"Bedroom-{tag}"
    finally:
        # Clean up only our own rows (rooms first for the FK), never the tables. Plain connection
        # (same owner role as the seed); suppress if seeding never happened.
        with contextlib.suppress(Exception), eng.begin() as conn:
            conn.execute(
                text("DELETE FROM c1.rooms WHERE room_id = ANY(:ids)"),
                {"ids": [kitchen, bedroom]},
            )
            conn.execute(
                text("DELETE FROM c1.houses WHERE house_id = ANY(:ids)"),
                {"ids": [maple, pine]},
            )
        eng.dispose()


# -- review item 5: a missing grant (42501) is re-raised, not returned as empty -------------
def test_insufficient_privilege_is_not_swallowed():
    eng = _engine()
    tbl = f"c1.probe_{uuid.uuid4().hex[:8]}"
    try:
        with eng.begin() as conn:
            with _role(conn, "c1_app"):
                conn.execute(text(f"CREATE TABLE {tbl} (house_id uuid, tenant_id uuid)"))
                conn.execute(text(f"REVOKE ALL ON {tbl} FROM c3_reader"))
            with _role(conn, "c3_reader"), pytest.raises(ProgrammingError):
                _safe_c1_query(conn, f"SELECT * FROM {tbl}", {})
    finally:
        with eng.begin() as conn, _role(conn, "c1_app"):
            conn.execute(text(f"DROP TABLE IF EXISTS {tbl}"))
        eng.dispose()


# -- audit 4.1: the scope columns the code assumes must exist on the real tables ------------
def test_scope_columns_match_live_schema():
    eng = _engine()
    table_of = {
        "houses": ("c1", "houses"),
        "rooms": ("c1", "rooms"),
        "feeds": ("c1", "camera_feeds"),
        "alerts": ("c2", "alerts"),
    }
    checked = 0
    try:
        with eng.connect() as conn, _role(conn, "c3_reader"):
            for entity, cols in SCOPE_COLUMNS.items():
                schema, table = table_of[entity]
                exists = conn.execute(
                    text("SELECT to_regclass(:q) IS NOT NULL"), {"q": f"{schema}.{table}"}
                ).scalar_one()
                if not exists:
                    continue  # table not shipped yet (c1 today) -> skip this entity
                present = {
                    r[0]
                    for r in conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = :s AND table_name = :t"
                        ),
                        {"s": schema, "t": table},
                    )
                }
                for assumed in cols:
                    if assumed == "tenant_via_house":
                        continue  # synthetic marker, not a column
                    assert assumed in present, (
                        f"{schema}.{table} is missing assumed scope column '{assumed}'"
                    )
                checked += 1
    finally:
        eng.dispose()
    # This is a guard, not a requirement that any cross-component table exist: C3's CI test job
    # migrates only schema c3, and c1/c2 tables live in their own jobs/DBs (and c1 has not
    # shipped). So zero tables to check is a valid no-op; the value is that IF a table exists,
    # its scope columns must match. It fires for real once c1/c2 share the DB (compose, RDS).
    if checked == 0:
        pytest.skip(
            "no c1.*/c2.* tables in this DB (per-service CI job); nothing to contract-check"
        )
