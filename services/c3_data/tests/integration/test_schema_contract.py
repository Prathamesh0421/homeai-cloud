"""C3-10 (Tier 2/3): cross-component schema assumptions and fail-closed behavior.

- Review item 1: rooms scope through their house so the tenant still applies (needs stand-in
  c1.houses / c1.rooms, which this test creates as c1_app and drops after; C1 has not shipped).
- Review item 5: a missing grant (42501) is re-raised, not swallowed as "C1 absent".
- Audit 4.1: an information_schema column contract — the SCOPE_COLUMNS the code assumes must
  exist on the real c1.*/c2.* tables; skips per table that is absent (c1 today), runs green when
  it ships, fails loudly if the shape differs.
"""

from __future__ import annotations

import os
import uuid

import pytest
from app.services.record_query import SCOPE_COLUMNS, RecordQuery
from app.services.record_scope import RecordScope
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

pytestmark = pytest.mark.integration


def _require(reason: str):
    if os.environ.get("CI") == "true":
        pytest.fail(f"integration store required on CI: {reason}", pytrace=False)
    pytest.skip(reason)


def _pg() -> str:
    pg = os.environ.get("DATABASE_URL_C3")
    if not pg:
        _require("DATABASE_URL_C3 not set")
    return pg


def _as_role(pg: str, role: str) -> str:
    """Swap only the userinfo role in the DSN, never the host.

    postgresql+psycopg://<role>:<pw>@<host>:<port>/<db> -> replace the role between '//' and ':'.
    """
    scheme, rest = pg.split("://", 1)
    userinfo, hostpart = rest.split("@", 1)
    _old_user, _, pw = userinfo.partition(":")
    return f"{scheme}://{role}:{pw or 'devpass'}@{hostpart}"


# -- review item 1: rooms scoped through house ---------------------------------------------
def test_rooms_scoped_through_house_by_tenant():
    pg = _pg()
    # Create stand-in c1.houses / c1.rooms as the c1 owner (c1 has not shipped its migration).
    owner = create_engine(_as_role(pg, "c1_app"), future=True)
    acme, sunrise = str(uuid.uuid4()), str(uuid.uuid4())
    maple, pine = str(uuid.uuid4()), str(uuid.uuid4())
    kitchen, bedroom = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        with owner.begin() as conn:
            try:
                conn.execute(
                    text(
                        "CREATE TABLE c1.houses (house_id uuid primary key, tenant_id uuid, "
                        "name text, created_at timestamptz default now(), deleted_at timestamptz)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE TABLE c1.rooms (room_id uuid primary key, house_id uuid, "
                        "name text, room_type text, created_at timestamptz default now())"
                    )
                )
            except ProgrammingError:
                owner.dispose()
                _require("cannot create stand-in c1 tables (c1 may have shipped; rerun suite)")
            conn.execute(text("GRANT SELECT ON c1.houses, c1.rooms TO c3_reader"))
            conn.execute(
                text("INSERT INTO c1.houses (house_id, tenant_id, name) VALUES (:h,:t,'Maple')"),
                {"h": maple, "t": acme},
            )
            conn.execute(
                text("INSERT INTO c1.houses (house_id, tenant_id, name) VALUES (:h,:t,'Pine')"),
                {"h": pine, "t": sunrise},
            )
            conn.execute(
                text(
                    "INSERT INTO c1.rooms (room_id, house_id, name, room_type) "
                    "VALUES (:r,:h,'Kitchen','kitchen')"
                ),
                {"r": kitchen, "h": maple},
            )
            conn.execute(
                text(
                    "INSERT INTO c1.rooms (room_id, house_id, name, room_type) "
                    "VALUES (:r,:h,'Bedroom','bedroom')"
                ),
                {"r": bedroom, "h": pine},
            )

        reader = create_engine(_as_role(pg, "c3_reader"), future=True)
        with reader.connect() as conn:
            q = RecordQuery(conn, None)
            # iot_staff of Acme (tenant only, no house list) sees only Acme's room.
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

            # cloud_staff with ?tenant_id=Sunrise sees only Sunrise's room.
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
        reader.dispose()
    finally:
        with owner.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS c1.rooms"))
            conn.execute(text("DROP TABLE IF EXISTS c1.houses"))
        owner.dispose()


# -- review item 5: a missing grant (42501) is re-raised, not returned as empty -------------
def test_insufficient_privilege_is_not_swallowed():
    pg = _pg()
    owner = create_engine(_as_role(pg, "c1_app"), future=True)
    tbl = f"c1.probe_{uuid.uuid4().hex[:8]}"
    try:
        with owner.begin() as conn:
            conn.execute(text(f"CREATE TABLE {tbl} (house_id uuid, tenant_id uuid)"))
            # Deliberately do NOT grant SELECT to c3_reader.
            conn.execute(text(f"REVOKE ALL ON {tbl} FROM c3_reader"))
        reader = create_engine(_as_role(pg, "c3_reader"), future=True)
        from app.services.record_query import _safe_c1_query

        with reader.connect() as conn, pytest.raises(ProgrammingError):
            _safe_c1_query(conn, f"SELECT * FROM {tbl}", {})
        reader.dispose()
    finally:
        with owner.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {tbl}"))
        owner.dispose()


# -- audit 4.1: the scope columns the code assumes must exist on the real tables ------------
def test_scope_columns_match_live_schema():
    pg = _pg()
    eng = create_engine(_as_role(pg, "c3_reader"), future=True)
    table_of = {
        "houses": ("c1", "houses"),
        "rooms": ("c1", "rooms"),
        "feeds": ("c1", "camera_feeds"),
        "alerts": ("c2", "alerts"),
    }
    checked = 0
    try:
        with eng.connect() as conn:
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
    # At least c2.alerts should exist on main; if nothing was checked, the DB is unexpectedly bare.
    assert checked >= 1
