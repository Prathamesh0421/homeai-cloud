"""C2-01: app factory, health endpoint, docs URLs, envelope and request id wiring."""

from __future__ import annotations

from homeai_common import auth


def _down():
    raise ConnectionError("db down")


def test_health_ok(client):
    r = client.get("/api/v1/health/c2")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok", "version": "test-sha"}


def test_health_degraded_is_503(make_client):
    r = make_client({"db": _down, "mongo": lambda: None}).get("/api/v1/health/c2")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "db": "error", "mongo": "ok", "version": "test-sha"}


def test_openapi_served_at_c2_docs_path(client):
    spec = client.get("/api/v1/docs/c2/openapi.json")
    assert spec.status_code == 200
    assert spec.json()["info"]["title"].startswith("HomeAI Cloud — C2")
    assert "/api/v1/health/c2" in spec.json()["paths"]
    assert client.get("/api/v1/docs/c2").status_code == 200


def test_unknown_route_uses_error_envelope(client):
    r = client.get("/api/v1/alerts-nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_request_id_echoed_and_generated(client):
    assert (
        client.get("/api/v1/health/c2", headers={"X-Request-Id": "r-1"}).headers["X-Request-Id"]
        == "r-1"
    )
    assert client.get("/api/v1/health/c2").headers["X-Request-Id"]


def test_startup_configures_jwks_and_db(client, settings):
    from homeai_common import db

    assert auth.get_jwks_cache().jwks_url == settings.jwks_url
    db.check_database()  # the in-memory SQLite engine from settings.database_url


def test_real_db_check_reports_unreachable_postgres(settings, monkeypatch):
    from app.main import create_app
    from fastapi.testclient import TestClient

    settings = settings.model_copy(
        update={"database_url": "postgresql+psycopg://u:p@127.0.0.1:1/homeai"}
    )
    with TestClient(create_app(settings)) as c:
        r = c.get("/api/v1/health/c2")
    assert r.status_code == 503
    assert r.json()["db"] == "error"
