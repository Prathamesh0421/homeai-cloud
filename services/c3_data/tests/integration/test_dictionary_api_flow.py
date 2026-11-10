"""C3-13 (Tier 2): data-dictionary endpoints end to end against real Postgres.

Generate from the live schema via the API, read it back grouped by component, export CSV, and
confirm re-publishing the same version is 409. cloud_staff only.
"""

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
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration


def _require(reason: str):
    if os.environ.get("CI") == "true":
        pytest.fail(f"integration store required on CI: {reason}", pytrace=False)
    pytest.skip(reason)


@pytest.fixture
def client_and_cleanup(monkeypatch):
    pg = os.environ.get("DATABASE_URL_C3")
    mongo = os.environ.get("MONGO_URL_C3")
    if not pg or not mongo:
        _require("DATABASE_URL_C3 / MONGO_URL_C3 not set")

    # Reader URL as c3_reader where the DSN is an app role; on CI the DSN is the superuser, which
    # reflects every schema fine.
    reader_url = pg
    for app_role in ("c3_app", "c4_app", "c2_app", "c1_app"):
        reader_url = reader_url.replace(f"{app_role}:", "c3_reader:")

    settings = Settings(
        env="test", database_url=pg, database_reader_url=reader_url, mongo_url=mongo, git_sha="it"
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

    def header(role):
        return {"Authorization": "Bearer " + mint_user_token(private, kid="test-key", role=role)}

    versions: list[str] = []
    yield client, header, versions
    client.__exit__(None, None, None)
    eng = create_engine(pg, future=True)
    with eng.begin() as conn:
        for v in versions:
            conn.execute(
                text("DELETE FROM c3.data_dictionary_versions WHERE version = :v"), {"v": v}
            )
    eng.dispose()


def test_generate_then_get_grouped_and_csv(client_and_cleanup):
    client, header, versions = client_and_cleanup
    version = f"it-{uuid.uuid4().hex[:8]}"
    versions.append(version)

    r = client.post(
        "/api/v1/data-dictionary",
        json={"version": version, "generate": True},
        headers=header("cloud_staff"),
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["entities"] > 0

    # GET latest, grouped by component.
    g = client.get("/api/v1/data-dictionary", headers=header("cloud_staff"))
    assert g.status_code == 200
    data = g.json()["data"]
    comps = {c["component"] for c in data["components"]}
    assert "c3" in comps
    c3 = next(c for c in data["components"] if c["component"] == "c3")
    entity_names = {e["name"] for e in c3["entities"]}
    assert "ml_models" in entity_names
    assert "activity_patterns" in entity_names

    # CSV export of that version.
    csv_resp = client.get(
        f"/api/v1/data-dictionary?version={version}&format=csv", headers=header("cloud_staff")
    )
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    body = csv_resp.text.splitlines()
    assert body[0].startswith("component,store,schema,entity,field,type")
    assert any(",activity_patterns,counted," in ln and ",true," in ln for ln in body)


def test_republish_same_version_is_409(client_and_cleanup):
    client, header, versions = client_and_cleanup
    version = f"it-{uuid.uuid4().hex[:8]}"
    versions.append(version)

    first = client.post(
        "/api/v1/data-dictionary",
        json={"version": version, "generate": True},
        headers=header("cloud_staff"),
    )
    assert first.status_code == 201
    again = client.post(
        "/api/v1/data-dictionary",
        json={"version": version, "generate": True},
        headers=header("cloud_staff"),
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "version_exists"


def test_get_when_empty_is_404(client_and_cleanup):
    client, header, _versions = client_and_cleanup
    # A version that does not exist -> 404 (does not touch the "latest" row).
    r = client.get(
        "/api/v1/data-dictionary?version=does-not-exist-xyz", headers=header("cloud_staff")
    )
    assert r.status_code == 404
