"""C3-12 (Tier 2): integrity endpoints end to end against real Postgres + Mongo.

Covers the documented contract (docs §3.2, §4.8): POST starts a check (202 {report_id}), the
background scan records findings and moves the report running -> done, GET reads it back, and a
second concurrent check for the same tenant is 409 check_running. TestClient runs background
tasks synchronously after the response, so the report is done by the time we GET it.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from app.main import create_app
from app.repositories.integrity_repo import IntegrityRepo
from app.settings import Settings
from fastapi.testclient import TestClient
from homeai_common import auth, db
from homeai_common.auth import JwksCache
from homeai_common.testing import make_test_keys, mint_user_token
from sqlalchemy import text

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

    mdb = raw.get_default_database()
    run_tenant = str(uuid.uuid4())

    settings = Settings(
        env="test", database_url=pg, database_reader_url=None, mongo_url=mongo, git_sha="it"
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

    def header(role, tenant_id=None):
        return {
            "Authorization": "Bearer "
            + mint_user_token(private, kid="test-key", role=role, tenant_id=tenant_id or run_tenant)
        }

    yield client, mdb, header, run_tenant
    client.__exit__(None, None, None)  # disposes the app's DB engine
    for col in ("ai_detections", "media_events", "activity_patterns"):
        mdb[col].delete_many({"tenant_id": run_tenant})
    # Clean this run's report rows via a standalone engine (the app's DB is now disposed).
    from sqlalchemy import create_engine

    engine = create_engine(pg, future=True)
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM c3.integrity_reports WHERE scope->>'tenant_id' = :t"),
            {"t": run_tenant},
        )
    engine.dispose()
    raw.close()


def test_run_check_flow_records_findings(client_and_db):
    client, mdb, header, t = client_and_db
    # Plant a high-severity fault for this tenant: analyzed clip with no detection_id.
    mdb["media_events"].insert_one(
        {
            "_id": str(uuid.uuid4()),
            "tenant_id": t,
            "house_id": "22222222-0000-0000-0000-0000000000a1",
            "status": "analyzed",
            "uploaded_at": datetime.now(UTC),
        }
    )

    r = client.post(f"/api/v1/integrity-checks?tenant_id={t}", headers=header("cloud_staff"))
    assert r.status_code == 202
    report_id = r.json()["data"]["report_id"]

    # Background scan ran synchronously after the response; the report is now done.
    g = client.get(f"/api/v1/integrity-reports/{report_id}", headers=header("cloud_staff"))
    assert g.status_code == 200
    report = g.json()["data"]
    assert report["status"] == "done"
    kinds = {f["kind"] for f in report["findings"]}
    assert "analyzed_no_detection" in kinds


def test_list_reports_returns_this_run(client_and_db):
    client, _mdb, header, t = client_and_db
    client.post(f"/api/v1/integrity-checks?tenant_id={t}", headers=header("cloud_staff"))
    r = client.get(f"/api/v1/integrity-reports?tenant_id={t}", headers=header("cloud_staff"))
    assert r.status_code == 200
    assert len(r.json()["data"]) >= 1


def test_concurrent_check_same_tenant_is_409(client_and_db):
    client, _mdb, header, t = client_and_db
    # Insert a running report directly so a POST collides on ux_one_running.
    with db.session_scope() as session:
        IntegrityRepo(session).start({"tenant_id": t}, requested_by=None)

    r = client.post(f"/api/v1/integrity-checks?tenant_id={t}", headers=header("cloud_staff"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "check_running"
