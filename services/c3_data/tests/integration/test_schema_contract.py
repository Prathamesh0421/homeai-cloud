"""C3-10 (Tier 2/3): cross-component schema assumptions and fail-closed behavior.

- Review item 1: rooms scope through their house so the tenant still applies. C1 has shipped, so
  this seeds C1's real c1.houses / c1.rooms and cleans up its own rows (never drops the tables).
- Review item 5: a missing grant (42501) is re-raised, not swallowed as "C1 absent".
- Audit 4.1: an information_schema column contract for the scope columns the code assumes.
- Audit 4.8 (C1-integration): the explicit c1 column lists the Records API selects must all
  exist in C1's live schema, so a C1 rename/drop fails loudly instead of leaking/breaking.
- media_events shape (4.5): C3's processing-field writes are pinned to C1's real writer shape.

Role model: these tests open one connection from DATABASE_URL_C3 and ``SET ROLE`` to switch. On
CI that DSN is the superuser, so SET ROLE works; locally it is c3_app, which may not be a member
of the other roles, so the switch is refused and the test skips (never silently passes). Tests
that need c1 tables skip when C1 is absent (per-package CI migrates only schema c3).
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


# -- audit 4.8 (C1-integration): explicit c1 column lists match C1's live schema ------------
def test_c1_select_columns_exist_in_live_schema():
    """Every column the Records API selects from a c1 table must exist in C1's real schema.

    Now that c1 reads use explicit lists (not SELECT *), a C1 rename or drop of a column we read
    should fail here loudly rather than surface as a 500 in production. Skips when c1 is absent
    (per-package CI). The c1.config / soft-delete columns are deliberately NOT in these lists, so
    this also documents what the Records API does not expose.
    """
    table_of = {"houses": "houses", "rooms": "rooms", "feeds": "camera_feeds"}
    eng = _engine()
    checked = 0
    try:
        with eng.connect() as conn, _role(conn, "c3_reader"):
            for entity, table in table_of.items():
                exists = conn.execute(
                    text("SELECT to_regclass(:q) IS NOT NULL"), {"q": f"c1.{table}"}
                ).scalar_one()
                if not exists:
                    continue
                present = {
                    r[0]
                    for r in conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = 'c1' AND table_name = :t"
                        ),
                        {"t": table},
                    )
                }
                # Parse the explicit SELECT list back into bare column names (strip casts/aliases).
                selected = RecordQuery._C1_COLUMNS[entity].replace("\n", " ")
                for raw in selected.split(","):
                    col = raw.strip().split("::")[0].split(" AS ")[0].strip()
                    assert col in present, f"c1.{table}: selected column '{col}' not in live schema"
                checked += 1
    finally:
        eng.dispose()
    if checked == 0:
        pytest.skip("no c1.* tables in this DB (per-package CI job); nothing to contract-check")


# -- 4.5: media_events shape pinned to C1's real writer -------------------------------------
def test_media_events_shape_matches_c1_writer():
    """C3's processing-field assumptions must match the document C1 actually writes.

    Pin to C1's real writer (``c1_iot ... new_media_event``) rather than a hand-made dict, so if
    C1 changes the media_events shape this contract fails. C3 only writes the processing fields;
    those must all be present on a freshly-written C1 document.
    """
    import importlib.util
    from datetime import UTC, datetime
    from pathlib import Path

    # Load C1's media_events writer by file path under a unique module name. We do NOT add
    # c1_iot to sys.path: its package is also called ``app`` and would collide with c3's. Loading
    # just this file (stdlib + pymongo imports only) pins us to C1's real shape without that clash.
    root = Path(__file__).resolve().parents[4]
    c1_file = root / "services" / "c1_iot" / "app" / "repositories" / "media_event_repo.py"
    if not c1_file.exists():
        pytest.skip("c1_iot media_event_repo not present in this checkout")
    spec = importlib.util.spec_from_file_location("c1_media_event_repo_contract", c1_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    c1_new_media_event = module.new_media_event

    doc = c1_new_media_event(
        media_id="m-1",
        tenant_id="t-1",
        house_id="h-1",
        room_id="r-1",
        feed_id="f-1",
        media_kind="audio",
        bucket="b",
        key="k",
        size=1,
        content_type="audio/wav",
        captured_at=datetime.now(UTC),
        uploaded_at=datetime.now(UTC),
        client_clip_id=None,
    )

    # The scope + identity fields C3 reads for records/integrity/rollup.
    for field in ("_id", "tenant_id", "house_id", "room_id", "feed_id"):
        assert field in doc, f"C1 media_events writer no longer emits '{field}'"
    # The processing fields C3 owns and updates (media_event_repo). C1 seeds them; C3 mutates.
    for field in (
        "status",
        "attempts",
        "claimed_at",
        "worker_id",
        "error",
        "detection_id",
        "handoff_status",
    ):
        assert field in doc, f"C1 media_events writer no longer seeds the C3 field '{field}'"
    # Initial values C3's claim/rollup logic assumes.
    assert doc["status"] == "queued"
    assert doc["attempts"] == 0
    assert doc["handoff_status"] == "none"
    assert doc["detection_id"] is None
