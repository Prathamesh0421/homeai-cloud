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
    eng = _engine()
    acme, sunrise = str(uuid.uuid4()), str(uuid.uuid4())
    maple, pine = str(uuid.uuid4()), str(uuid.uuid4())
    kitchen, bedroom = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        with eng.begin() as conn:
            # Create stand-in c1 tables as the c1 owner (c1 has not shipped its migration).
            with _role(conn, "c1_app"):
                try:
                    conn.execute(
                        text(
                            "CREATE TABLE c1.houses (house_id uuid primary key, tenant_id uuid, "
                            "name text, created_at timestamptz default now(), "
                            "deleted_at timestamptz)"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE TABLE c1.rooms (room_id uuid primary key, house_id uuid, "
                            "name text, room_type text, created_at timestamptz default now())"
                        )
                    )
                except ProgrammingError:
                    pytest.skip("cannot create stand-in c1 tables (c1 may have shipped)")
                conn.execute(text("GRANT SELECT ON c1.houses, c1.rooms TO c3_reader"))
                conn.execute(
                    text(
                        "INSERT INTO c1.houses (house_id, tenant_id, name) VALUES "
                        "(:h1,:t1,'Maple'), (:h2,:t2,'Pine')"
                    ),
                    {"h1": maple, "t1": acme, "h2": pine, "t2": sunrise},
                )
                conn.execute(
                    text(
                        "INSERT INTO c1.rooms (room_id, house_id, name, room_type) VALUES "
                        "(:r1,:h1,'Kitchen','kitchen'), (:r2,:h2,'Bedroom','bedroom')"
                    ),
                    {"r1": kitchen, "h1": maple, "r2": bedroom, "h2": pine},
                )

            # Read as c3_reader (the role the Records API uses).
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
                assert rows[0]["name"] == "Kitchen"

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
                assert rows[0]["name"] == "Bedroom"
    finally:
        with eng.begin() as conn, _role(conn, "c1_app"):
            conn.execute(text("DROP TABLE IF EXISTS c1.rooms"))
            conn.execute(text("DROP TABLE IF EXISTS c1.houses"))
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
    assert checked >= 1  # c2.alerts exists on main; a bare DB is a misconfig
