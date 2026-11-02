"""API tests: service-token issuance and scope checks."""

from __future__ import annotations

import bcrypt
from app.models.orm import ServiceClient
from sqlalchemy.orm import Session

from tests.conftest import skip_no_postgres


def _seed_client(
    db_session: Session, *, client_id: str, secret: str, scopes: list[str]
) -> ServiceClient:
    client = ServiceClient(
        client_id=client_id,
        secret_hash=bcrypt.hashpw(secret.encode(), bcrypt.gensalt()).decode(),
        scopes=scopes,
    )
    db_session.add(client)
    db_session.commit()
    return client


@skip_no_postgres
def test_service_token_success(client, db_session):
    _seed_client(
        db_session, client_id="c3-worker", secret="dev-c3-secret", scopes=["alerts:evaluate"]
    )
    resp = client.post(
        "/api/v1/auth/service-token",
        json={
            "client_id": "c3-worker",
            "client_secret": "dev-c3-secret",
            "scope": ["alerts:evaluate"],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["expires_in"] == 900
    assert data["token"].count(".") == 2


@skip_no_postgres
def test_service_token_wrong_secret_returns_401(client, db_session):
    _seed_client(
        db_session, client_id="c3-worker", secret="dev-c3-secret", scopes=["alerts:evaluate"]
    )
    resp = client.post(
        "/api/v1/auth/service-token",
        json={
            "client_id": "c3-worker",
            "client_secret": "wrong",
            "scope": ["alerts:evaluate"],
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"


@skip_no_postgres
def test_service_token_unknown_client_returns_401(client, db_session):
    resp = client.post(
        "/api/v1/auth/service-token",
        json={
            "client_id": "ghost",
            "client_secret": "x",
            "scope": [],
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"


@skip_no_postgres
def test_service_token_disallowed_scope_returns_403(client, db_session):
    _seed_client(
        db_session, client_id="c2-alerts", secret="dev-c2-secret", scopes=["clips:playback"]
    )
    resp = client.post(
        "/api/v1/auth/service-token",
        json={
            "client_id": "c2-alerts",
            "client_secret": "dev-c2-secret",
            "scope": ["alerts:evaluate"],
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"
    details = resp.json()["error"]["details"]
    assert "alerts:evaluate" in details["requested"]


@skip_no_postgres
def test_revoked_endpoint_requires_service_token(client, db_session):
    _seed_client(
        db_session, client_id="c3-worker", secret="dev-c3-secret", scopes=["alerts:evaluate"]
    )
    resp = client.post(
        "/api/v1/auth/service-token",
        json={
            "client_id": "c3-worker",
            "client_secret": "dev-c3-secret",
            "scope": ["alerts:evaluate"],
        },
    )
    token = resp.json()["data"]["token"]
    rev = client.get("/api/v1/auth/revoked", headers={"Authorization": f"Bearer {token}"})
    assert rev.status_code == 200, rev.text
    assert "jti" in rev.json()["data"]
