"""Error envelope mapping (contracts §1, §1.1), including homeai_common.auth's HTTPExceptions."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from homeai_common import auth
from homeai_common.auth import JwksCache, Principal, require_roles
from homeai_common.errors import ApiError, ErrorEnvelope, error_envelope, install_error_handlers
from homeai_common.logging import RequestIdMiddleware
from homeai_common.testing import make_test_keys, mint_user_token
from pydantic import BaseModel, Field


class RuleIn(BaseModel):
    min_confidence: float = Field(ge=0, le=1)
    password: str


def build_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(RequestIdMiddleware)

    @app.get("/api-error")
    def api_error():
        raise ApiError(409, "duplicate_rule", "rule exists", {"rule_id": "r1"})

    @app.get("/api-error-headers")
    def api_error_headers():
        raise ApiError(429, "rate_limited", "slow down", headers={"Retry-After": "30"})

    @app.get("/http-dict")
    def http_dict():
        raise HTTPException(401, detail={"code": "token_expired", "message": "token expired"})

    @app.get("/http-plain")
    def http_plain():
        raise HTTPException(403, detail="nope", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/http-unmapped")
    def http_unmapped():
        raise HTTPException(418, detail="teapot")

    @app.post("/rules")
    def create_rule(body: RuleIn):
        return {"data": body.model_dump()}

    @app.get("/items")
    def items(page: int):
        return {"data": page}

    @app.get("/crash")
    def crash():
        raise RuntimeError("boom")

    @app.get("/owner-only")
    def owner_only(p: Principal = Depends(require_roles("house_owner"))):
        return {"data": p.sub}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(), raise_server_exceptions=False)


def test_api_error_uses_envelope(client):
    r = client.get("/api-error")
    assert r.status_code == 409
    assert r.json() == {
        "error": {"code": "duplicate_rule", "message": "rule exists", "details": {"rule_id": "r1"}}
    }


def test_api_error_keeps_headers(client):
    r = client.get("/api-error-headers")
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "30"
    assert "details" not in r.json()["error"]


def test_http_exception_dict_detail_is_unwrapped(client):
    r = client.get("/http-dict")
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "token_expired", "message": "token expired"}}


def test_http_exception_plain_detail_gets_default_code_and_headers(client):
    r = client.get("/http-plain")
    assert r.status_code == 403
    assert r.json() == {"error": {"code": "forbidden", "message": "nope"}}
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_http_exception_unknown_status_gets_generic_code(client):
    r = client.get("/http-unmapped")
    assert r.json()["error"]["code"] == "http_error"


def test_unknown_route_and_method_use_envelope(client):
    r = client.get("/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    r = client.delete("/api-error")
    assert r.status_code == 405
    assert r.json()["error"]["code"] == "method_not_allowed"


def test_validation_error_maps_fields_and_never_echoes_input(client):
    r = client.post("/rules", json={"min_confidence": 1.5, "password": 123})
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_error"
    fields = {d["field"] for d in body["details"]}
    assert fields == {"min_confidence", "password"}
    assert all(set(d) == {"field", "issue"} for d in body["details"])
    assert "123" not in r.text


def test_validation_error_on_query_param(client):
    r = client.get("/items", params={"page": "abc"})
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == "page"


def test_missing_body_reports_body_field(client):
    r = client.post("/rules")
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == "body"


def test_unhandled_exception_is_500_envelope_with_request_id(client):
    r = client.get("/crash", headers={"X-Request-Id": "req-123"})
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "internal_error", "message": "unexpected error"}}
    assert r.headers["X-Request-Id"] == "req-123"
    assert "boom" not in r.text


def test_error_envelope_helper_and_model():
    env = error_envelope("not_found", "missing")
    assert env == {"error": {"code": "not_found", "message": "missing"}}
    assert ErrorEnvelope.model_validate(env).error.code == "not_found"


# --- integration with homeai_common.auth (P0-4) -------------------------------------------


class _StaticJwks(JwksCache):
    def __init__(self, entry):
        super().__init__(jwks_url="static")
        self._keys = {entry["kid"]: entry}
        self._fetched_at = 1e12

    def _refresh(self):
        pass


@pytest.fixture
def private_key(monkeypatch):
    private, _public, entry = make_test_keys(kid="test-key")
    monkeypatch.setattr(auth, "_default_cache", _StaticJwks(entry))
    return private


def test_auth_missing_bearer_is_401_envelope(client, private_key):
    r = client.get("/owner-only")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_auth_wrong_role_is_403_envelope(client, private_key):
    token = mint_user_token(private_key, kid="test-key", role="iot_staff")
    r = client.get("/owner-only", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_auth_expired_token_is_token_expired_envelope(client, private_key):
    token = mint_user_token(private_key, kid="test-key", role="house_owner", ttl_seconds=-120)
    r = client.get("/owner-only", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "token_expired"


def test_auth_valid_token_passes(client, private_key):
    token = mint_user_token(private_key, kid="test-key", user_id="u1", role="house_owner")
    r = client.get("/owner-only", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == {"data": "u1"}
