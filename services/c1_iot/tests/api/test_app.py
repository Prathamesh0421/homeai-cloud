"""App wiring without infrastructure: health, docs, auth envelope, role checks."""

from __future__ import annotations

from tests.factories import HOUSE_A1, TENANT_A


def test_health_ok(client):
    resp = client.get("/api/v1/health/c1")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok", "version": "test-sha"}


def test_health_degraded_is_503(make_client):
    def broken() -> None:
        raise RuntimeError("down")

    client = make_client({"db": lambda: None, "mongo": broken})
    resp = client.get("/api/v1/health/c1")
    assert resp.status_code == 503
    assert resp.json()["mongo"] == "error"


def test_openapi_docs_render(client):
    assert client.get("/api/v1/docs/c1").status_code == 200
    paths = client.get("/api/v1/docs/c1/openapi.json").json()["paths"]
    assert "/api/v1/houses" in paths
    assert "/api/v1/rooms/{room_id}" in paths


def test_missing_token_is_401_with_envelope(client):
    resp = client.get("/api/v1/houses")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
    assert resp.headers["X-Request-Id"]


def test_owner_cannot_create_house(client, auth_header):
    owner = auth_header(role="house_owner", tenant_id=TENANT_A, house_ids=[HOUSE_A1])
    resp = client.post("/api/v1/houses", json={"name": "X", "timezone": "UTC"}, headers=owner)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_service_token_cannot_list_houses(client, auth_header):
    resp = client.get("/api/v1/houses", headers=auth_header(service_scopes=["feeds:read"]))
    assert resp.status_code == 403


def test_bad_uuid_in_path_is_422(client, auth_header):
    staff = auth_header(role="iot_staff", tenant_id=TENANT_A)
    resp = client.get("/api/v1/houses/not-a-uuid", headers=staff)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
