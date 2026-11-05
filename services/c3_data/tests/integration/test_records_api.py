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
    run_tenant = f"t-{uuid.uuid4().hex[:8]}"

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


def _detection(tenant, house, label="glass_break", when=None):
    return {
        "_id": str(uuid.uuid4()),
        "media_id": str(uuid.uuid4()),
        "tenant_id": tenant,
        "house_id": house,
        "room_id": "r1",
        "model": {"model_id": "m1", "name": "yamnet", "version": "1.0.0"},
        "labels": [],
        "top_label": label,
        "top_confidence": 0.8,
        "detected_at": when or datetime.now(UTC),
    }


def test_detections_scoped_by_tenant_and_house(client_and_db):
    client, db, header, t = client_and_db
    db["ai_detections"].insert_many(
        [_detection(t, "maple"), _detection(t, "maple", "dog"), _detection(t, "oak")]
    )

    r = client.get(f"/api/v1/records/detections?tenant_id={t}", headers=header("cloud_staff"))
    assert r.status_code == 200
    assert r.json()["meta"]["total"] == 3

    # owner of maple sees only maple detections (2).
    r = client.get("/api/v1/records/detections", headers=header("house_owner", t, ["maple"]))
    assert r.json()["meta"]["total"] == 2

    # owner of oak cannot see maple's by passing another house (tenant isolation).
    r = client.get(
        "/api/v1/records/detections?house_id=maple",
        headers=header("house_owner", t, ["oak"]),
    )
    assert r.json()["meta"]["total"] == 0


def test_unknown_entity_404(client_and_db):
    client, _db, header, _t = client_and_db
    r = client.get("/api/v1/records/nope", headers=header("cloud_staff"))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "unknown_entity"


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
        [_detection(t, "maple", "glass_break"), _detection(t, "maple", "dog")]
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
            _detection(t, "maple", "glass_break"),
            _detection(t, "maple", "glass_break"),
            _detection(t, "maple", "dog"),
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
