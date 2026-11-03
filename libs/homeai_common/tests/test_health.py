"""health_router: contract body, 503 on a failed check."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from homeai_common.health import health_router


def _client(checks) -> TestClient:
    app = FastAPI()
    app.include_router(health_router("c2", checks, version="abc123"))
    return TestClient(app)


def _fail():
    raise ConnectionError("down")


def test_all_ok_matches_contract():
    r = _client({"db": lambda: None, "mongo": lambda: None}).get("/api/v1/health/c2")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok", "mongo": "ok", "version": "abc123"}


def test_failed_check_is_503_degraded():
    r = _client({"db": lambda: None, "mongo": _fail}).get("/api/v1/health/c2")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "db": "ok", "mongo": "error", "version": "abc123"}


def test_no_checks_is_ok():
    r = _client({}).get("/api/v1/health/c2")
    assert r.json() == {"status": "ok", "version": "abc123"}
