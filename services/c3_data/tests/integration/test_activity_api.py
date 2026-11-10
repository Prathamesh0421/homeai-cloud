"""C3-11 (Tier 2): GET /activity-patterns scope on real Mongo (Rev3 §6.2)."""

from __future__ import annotations

import os
import uuid

import pytest
from app.main import create_app
from app.settings import Settings
from fastapi.testclient import TestClient
from homeai_common import auth
from homeai_common.auth import JwksCache
from homeai_common.testing import make_test_keys, mint_user_token

pytestmark = pytest.mark.integration

MAPLE = "22222222-0000-0000-0000-0000000000a1"
OAK = "22222222-0000-0000-0000-0000000000a2"
ROOM = "33333333-0000-0000-0000-0000000000a1"


def _require(reason: str):
    if os.environ.get("CI") == "true":
        pytest.fail(f"integration store required on CI: {reason}", pytrace=False)
    pytest.skip(reason)


@pytest.fixture
def client_db(monkeypatch):
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
    tenant = str(uuid.uuid4())

    app = create_app(Settings(env="test", database_url=pg, mongo_url=mongo, git_sha="it"))
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

    def header(role, house_ids=()):
        return {
            "Authorization": "Bearer "
            + mint_user_token(
                private, kid="test-key", role=role, tenant_id=tenant, house_ids=list(house_ids)
            )
        }

    yield client, db, header, tenant
    client.__exit__(None, None, None)
    db["activity_patterns"].delete_many({"tenant_id": tenant})
    raw.close()


def _pattern(tenant, house, date="2026-06-01", hour=14, count=3):
    hours = [0] * 24
    hours[hour] = count
    return {
        "_id": f"{house}:{ROOM}:{date}",
        "tenant_id": tenant,
        "house_id": house,
        "room_id": ROOM,
        "date": date,
        "hours": hours,
        "counted": [],
    }


def test_owner_reads_own_house(client_db):
    client, db, header, t = client_db
    db["activity_patterns"].insert_one(_pattern(t, MAPLE))
    r = client.get(
        f"/api/v1/activity-patterns?house_id={MAPLE}&date=2026-06-01",
        headers=header("house_owner", [MAPLE]),
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["hours"][14] == 3


def test_owner_cannot_read_other_house(client_db):
    client, db, header, t = client_db
    db["activity_patterns"].insert_one(_pattern(t, OAK))
    # Owner of Maple asks for Oak (same tenant) -> empty, no disclosure.
    r = client.get(
        f"/api/v1/activity-patterns?house_id={OAK}&date=2026-06-01",
        headers=header("house_owner", [MAPLE]),
    )
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_iot_staff_forbidden(client_db):
    client, _db, header, _t = client_db
    r = client.get(f"/api/v1/activity-patterns?house_id={MAPLE}", headers=header("iot_staff"))
    assert r.status_code == 403


def test_bad_house_id_422(client_db):
    client, _db, header, _t = client_db
    r = client.get("/api/v1/activity-patterns?house_id=not-a-uuid", headers=header("cloud_staff"))
    assert r.status_code == 422


def test_cloud_staff_reads_any_house(client_db):
    client, db, header, t = client_db
    db["activity_patterns"].insert_one(_pattern(t, OAK, date="2026-06-02"))
    r = client.get(
        f"/api/v1/activity-patterns?house_id={OAK}&date=2026-06-02",
        headers=header("cloud_staff"),
    )
    assert r.status_code == 200
    assert len(r.json()["data"]) == 1
