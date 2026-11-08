"""C3-10 (Tier 2): Records API + /detections/stats against real Mongo + Postgres.

Exercises scope/tenant isolation, C1-absent -> empty (not error), unknown_entity 404, iot_staff
alerts 403, the per-user rate limit, and stats grouping. SQL entities read via the c3_reader
reader engine; c1.* tables don't exist yet, so houses/rooms/feeds come back empty by design.

c3_app is scoped to the homeai database, so writes go to the app's collections and are isolated
by a unique tenant id per run (teardown deletes only this run's docs).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from app.main import create_app
from app.settings import Settings
from fastapi.testclient import TestClient
from homeai_common import auth
from homeai_common.auth import JwksCache
from homeai_common.testing import make_test_keys, mint_user_token

pytestmark = pytest.mark.integration


def _require(reason: str):
    if os.environ.get("CI") == "true":
        pytest.fail(f"integration store required on CI: {reason}", pytrace=False)
    pytest.skip(reason)


@pytest.fixture
def client_and_db(monkeypatch):
    pg = os.environ.get("DATABASE_URL_C3")
    mongo = os.environ.get("MONGO_URL_C3")
    if not pg or not mongo:
        _require("DATABASE_URL_C3 / MONGO_URL_C3 not set")

    from pymongo import MongoClient

    raw = MongoClient(mongo, serverSelectionTimeoutMS=2000)
    try:
        raw.admin.command("ping")
    except Exception as exc:
        _require(f"Mongo unreachable: {type(exc).__name__}")

    db = raw.get_default_database()
    run_tenant = str(uuid.uuid4())  # real UUID: tenant_id query param is UuidStr-validated

    # The Records API uses the c3_reader role for SQL entities; mirror that in the reader URL.
    reader_url = pg
    for app_role in ("c3_app", "c4_app", "c2_app", "c1_app"):
        reader_url = reader_url.replace(f"{app_role}:", "c3_reader:")

    settings = Settings(
        env="test",
        database_url=pg,
        database_reader_url=reader_url,
        mongo_url=mongo,
        git_sha="it",
    )
    app = create_app(settings)
    client = TestClient(app, raise_server_exceptions=False)
    client.__enter__()

    private, _pub, entry = make_test_keys(kid="test-key")

    class _StaticJwks(JwksCache):
        def __init__(self):
            super().__init__(jwks_url="static")
            self._keys = {entry["kid"]: entry}
            self._fetched_at = 1e12

        def _refresh(self):
            pass

    monkeypatch.setattr(auth, "_default_cache", _StaticJwks())

    def header(role, tenant_id=None, house_ids=()):
        return {
            "Authorization": "Bearer "
            + mint_user_token(
                private,
                kid="test-key",
                role=role,
                tenant_id=tenant_id or run_tenant,
                house_ids=list(house_ids),
            )
        }

    yield client, db, header, run_tenant
    client.__exit__(None, None, None)
    for col in ("ai_detections", "media_events", "activity_patterns"):
        db[col].delete_many({"tenant_id": run_tenant})
    raw.close()


# Fixed UUIDs so ?house_id= / ?tenant_id= query params pass UuidStr validation.
MAPLE = "22222222-0000-0000-0000-0000000000a1"
OAK = "22222222-0000-0000-0000-0000000000a2"
PINE = "22222222-0000-0000-0000-0000000000a3"
ROOM = "33333333-0000-0000-0000-0000000000a1"
OTHER_T = "11111111-0000-0000-0000-0000000000ff"  # a different tenant, for isolation tests


def _detection(tenant, house, label="glass_break", when=None):
    return {
        "_id": str(uuid.uuid4()),
        "media_id": str(uuid.uuid4()),
        "tenant_id": tenant,
        "house_id": house,
        "room_id": ROOM,
        "model": {"model_id": "m1", "name": "yamnet", "version": "1.0.0"},
        "labels": [],
        "top_label": label,
        "top_confidence": 0.8,
        "detected_at": when or datetime.now(UTC),
    }


def test_detections_scoped_by_tenant_and_house(client_and_db):
    client, db, header, t = client_and_db
    db["ai_detections"].insert_many(
        [_detection(t, MAPLE), _detection(t, MAPLE, "dog"), _detection(t, OAK)]
    )

    r = client.get(f"/api/v1/records/detections?tenant_id={t}", headers=header("cloud_staff"))
    assert r.status_code == 200
    assert r.json()["meta"]["total"] == 3

    # owner of maple sees only maple detections (2).
    r = client.get("/api/v1/records/detections", headers=header("house_owner", t, [MAPLE]))
    assert r.json()["meta"]["total"] == 2

    # owner of oak cannot see maple's by passing another house (tenant isolation).
    r = client.get(
        "/api/v1/records/detections?house_id=" + MAPLE + "",
        headers=header("house_owner", t, [OAK]),
    )
    assert r.json()["meta"]["total"] == 0


def test_unknown_entity_404(client_and_db):
    client, _db, header, _t = client_and_db
    r = client.get("/api/v1/records/nope", headers=header("cloud_staff"))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "unknown_entity"


# -- audit 4.4: get-by-id must not leak across tenants -------------------------------------
def test_get_detection_of_another_tenant_is_404(client_and_db):
    client, db, header, t = client_and_db
    foreign = _detection(OTHER_T, PINE)
    db["ai_detections"].insert_one(foreign)
    # An owner in tenant t requests the foreign tenant's detection by id -> 404, not 200.
    r = client.get(
        f"/api/v1/records/detections/{foreign['_id']}",
        headers=header("house_owner", t, [MAPLE]),
    )
    assert r.status_code == 404
    # Clean up the foreign-tenant doc (fixture teardown only removes this run's tenant).
    db["ai_detections"].delete_one({"_id": foreign["_id"]})


def test_c1_tables_absent_return_empty(client_and_db):
    client, _db, header, _t = client_and_db
    for entity in ("houses", "rooms", "feeds"):
        r = client.get(f"/api/v1/records/{entity}", headers=header("cloud_staff"))
        assert r.status_code == 200, r.text
        assert r.json()["data"] == []
        assert r.json()["meta"]["total"] == 0


def test_iot_staff_cannot_read_alerts(client_and_db):
    client, _db, header, _t = client_and_db
    r = client.get("/api/v1/records/alerts", headers=header("iot_staff"))
    assert r.status_code == 403


def test_bad_field_filter_422(client_and_db):
    client, _db, header, _t = client_and_db
    r = client.get("/api/v1/records/detections?filter=not_allowed:x", headers=header("cloud_staff"))
    assert r.status_code == 422


def test_detection_filter_whitelist_top_label(client_and_db):
    client, db, header, t = client_and_db
    db["ai_detections"].insert_many(
        [_detection(t, MAPLE, "glass_break"), _detection(t, MAPLE, "dog")]
    )
    r = client.get(
        f"/api/v1/records/detections?tenant_id={t}&filter=top_label:dog",
        headers=header("cloud_staff"),
    )
    assert r.json()["meta"]["total"] == 1
    assert r.json()["data"][0]["top_label"] == "dog"


def test_detections_stats_group_by_top_label(client_and_db):
    client, db, header, t = client_and_db
    db["ai_detections"].insert_many(
        [
            _detection(t, MAPLE, "glass_break"),
            _detection(t, MAPLE, "glass_break"),
            _detection(t, MAPLE, "dog"),
        ]
    )
    r = client.get(
        f"/api/v1/detections/stats?group_by=top_label&tenant_id={t}",
        headers=header("cloud_staff"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meta"]["total_clips"] == 3
    counts = {b["key"]: b["count"] for b in body["data"]}
    assert counts["glass_break"] == 2
    assert counts["dog"] == 1


def test_rate_limit_429(client_and_db):
    client, _db, header, _t = client_and_db
    h = header("cloud_staff")
    # The limiter allows 60/min/user; the 61st in the same window is blocked.
    statuses = [client.get("/api/v1/records/detections", headers=h).status_code for _ in range(61)]
    assert 429 in statuses
    assert statuses.count(200) <= 60


# -- review item 2: stats honours the owner's house scope ----------------------------------
def test_stats_house_id_out_of_scope_is_empty(client_and_db):
    client, db, header, t = client_and_db
    # Owner of maple; seed Oak (same tenant) detections they must not see via ?house_id=oak.
    db["ai_detections"].insert_many(
        [_detection(t, OAK), _detection(t, OAK), _detection(t, OAK), _detection(t, MAPLE)]
    )
    r = client.get(
        "/api/v1/detections/stats?group_by=top_label&house_id=" + OAK,
        headers=header("house_owner", t, [MAPLE]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"] == []
    assert r.json()["meta"]["total_clips"] == 0


# -- review item 3: malformed ids are 422, not 500 -----------------------------------------
def test_bad_house_id_is_422(client_and_db):
    client, _db, header, _t = client_and_db
    r = client.get("/api/v1/records/alerts?house_id=not-a-uuid", headers=header("cloud_staff"))
    assert r.status_code == 422


def test_bad_record_id_is_422(client_and_db):
    client, _db, header, _t = client_and_db
    r = client.get("/api/v1/records/detections/not-a-uuid", headers=header("cloud_staff"))
    assert r.status_code == 422


# -- review item 4: alerts explicit columns, numerics as numbers, tenant isolation ---------
def _seed_alert(conn, tenant, house, detection_id):
    from sqlalchemy import text

    # c2.alerts has FKs to alert_types (alert_type_id=1, from C2's seed) and alert_rules; seed a
    # minimal rule row to satisfy alerts_rule_id_fkey.
    rule_id = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO c2.alert_rules (rule_id, tenant_id, alert_type_id, trigger_labels, "
            "min_confidence, created_by) VALUES "
            "(:rid, :t, 1, ARRAY['glass_break'], 0.55, :cb)"
        ),
        {"rid": rule_id, "t": tenant, "cb": str(uuid.uuid4())},
    )
    conn.execute(
        text(
            "INSERT INTO c2.alerts (alert_id, tenant_id, house_id, room_id, alert_type_id, "
            "rule_id, detection_id, media_id, top_label, top_confidence, severity, status, "
            "triggered_at, updated_at, threshold) VALUES "
            "(:aid, :t, :h, NULL, 1, :rid, :did, :mid, 'glass_break', 0.780, 'high', 'open', "
            "now(), now(), 0.55)"
        ),
        {
            "aid": str(uuid.uuid4()),
            "t": tenant,
            "h": house,
            "rid": rule_id,
            "did": detection_id,
            "mid": str(uuid.uuid4()),
        },
    )


def test_alerts_numeric_columns_are_numbers_and_tenant_scoped(client_and_db):
    client, _db, header, t = client_and_db
    import os

    from sqlalchemy import create_engine, text

    # Seed/clean c2.alerts as a privileged role (c3_app cannot write c2); swap the role in the DSN.
    pg = os.environ["DATABASE_URL_C3"]
    scheme, rest = pg.split("://", 1)
    _userinfo, hostpart = rest.split("@", 1)
    admin_url = f"{scheme}://postgres:postgres@{hostpart}"
    eng = create_engine(admin_url, future=True)
    with eng.begin() as conn:
        has_alerts = conn.execute(text("SELECT to_regclass('c2.alerts') IS NOT NULL")).scalar_one()
        has_type = False
        if has_alerts:
            has_type = (
                conn.execute(
                    text("SELECT count(*) FROM c2.alert_types WHERE alert_type_id = 1")
                ).scalar_one()
                > 0
            )
        if not (has_alerts and has_type):
            eng.dispose()
            pytest.skip("c2.alerts / alert_types not available in this DB")
        _seed_alert(conn, t, MAPLE, str(uuid.uuid4()))
        _seed_alert(conn, OTHER_T, PINE, str(uuid.uuid4()))

    try:
        # cloud_staff narrowed to my tenant sees exactly my alert, with numeric fields.
        r = client.get(f"/api/v1/records/alerts?tenant_id={t}", headers=header("cloud_staff"))
        assert r.status_code == 200, r.text
        rows = r.json()["data"]
        assert len(rows) == 1
        a = rows[0]
        assert isinstance(a["top_confidence"], (int, float))  # not "0.780"
        assert isinstance(a["threshold"], (int, float))
        assert "rule_id" not in a and "updated_at" not in a  # C2 internals omitted
    finally:
        with eng.begin() as conn:
            conn.execute(
                text("DELETE FROM c2.alerts WHERE tenant_id IN (:a, :b)"),
                {"a": t, "b": OTHER_T},
            )
            conn.execute(
                text("DELETE FROM c2.alert_rules WHERE tenant_id IN (:a, :b)"),
                {"a": t, "b": OTHER_T},
            )
        eng.dispose()
