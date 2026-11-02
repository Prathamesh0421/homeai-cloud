"""API tests: login, lockout, logout, /auth/me, /auth/revoked."""

from __future__ import annotations

from uuid import uuid4

import bcrypt
import jwt
from app.models.orm import Tenant, User
from sqlalchemy.orm import Session

from tests.conftest import skip_no_postgres


def _seed_user(
    db_session: Session,
    *,
    email: str,
    role: str = "house_owner",
    password: str = "Demo!2026",
    is_active: bool = True,
) -> User:
    tenant = Tenant(name=f"t-{uuid4()}", timezone="UTC")
    db_session.add(tenant)
    db_session.flush()
    user = User(
        tenant_id=tenant.tenant_id,
        email=email,
        password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        role=role,
        is_active=is_active,
    )
    db_session.add(user)
    db_session.flush()
    return user


@skip_no_postgres
def test_login_success(client, db_session, issuer):
    _seed_user(db_session, email="owner@acme.test")
    db_session.commit()
    resp = client.post(
        "/api/v1/auth/login", json={"email": "owner@acme.test", "password": "Demo!2026"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["expires_in"] == 3600
    assert data["landing"] == "/home/overview"
    claims = jwt.decode(data["token"], options={"verify_signature": False})
    assert claims["role"] == "house_owner"
    assert claims["email"] == "owner@acme.test"
    assert claims["jti"] == data["claims"]["jti"]


@skip_no_postgres
def test_login_wrong_password_returns_401_invalid_credentials(client, db_session):
    _seed_user(db_session, email="owner@acme.test")
    db_session.commit()
    resp = client.post("/api/v1/auth/login", json={"email": "owner@acme.test", "password": "nope"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"


@skip_no_postgres
def test_login_unknown_email_returns_same_401(client, db_session):
    resp = client.post(
        "/api/v1/auth/login", json={"email": "ghost@acme.test", "password": "Demo!2026"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"


@skip_no_postgres
def test_login_inactive_user_returns_401(client, db_session):
    _seed_user(db_session, email="owner@acme.test", is_active=False)
    db_session.commit()
    resp = client.post(
        "/api/v1/auth/login", json={"email": "owner@acme.test", "password": "Demo!2026"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"


@skip_no_postgres
def test_login_locks_after_five_failures(client, db_session):
    _seed_user(db_session, email="owner@acme.test")
    db_session.commit()
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"email": "owner@acme.test", "password": "bad"})
    resp = client.post(
        "/api/v1/auth/login", json={"email": "owner@acme.test", "password": "Demo!2026"}
    )
    assert resp.status_code == 423
    assert resp.json()["error"]["code"] == "account_locked"
    assert resp.json()["error"]["details"]["retry_after"] >= 1


@skip_no_postgres
def test_logout_adds_jti_to_revoked_list(client, db_session):
    _seed_user(db_session, email="owner@acme.test")
    db_session.commit()
    login = client.post(
        "/api/v1/auth/login", json={"email": "owner@acme.test", "password": "Demo!2026"}
    )
    token = login.json()["data"]["token"]
    resp = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 204
    # /auth/me should now reject the token as revoked.
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 401
    assert me.json()["error"]["code"] == "token_revoked"


@skip_no_postgres
def test_auth_me_returns_user_and_houses(client, db_session):
    _seed_user(db_session, email="owner@acme.test")
    db_session.commit()
    login = client.post(
        "/api/v1/auth/login", json={"email": "owner@acme.test", "password": "Demo!2026"}
    )
    token = login.json()["data"]["token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    data = me.json()["data"]
    assert data["user"]["email"] == "owner@acme.test"
    assert data["user"]["role"] == "house_owner"
    # No c1.houses in this test env → names are null but ids are present.
    assert isinstance(data["houses"], list)


@skip_no_postgres
def test_auth_me_rejects_service_token(client, db_session, issuer):
    # Seed a service client and mint a token.
    from app.models.orm import ServiceClient

    client_id = "c3-worker"
    db_session.add(
        ServiceClient(
            client_id=client_id,
            secret_hash=bcrypt.hashpw(b"dev-c3-secret", bcrypt.gensalt()).decode(),
            scopes=["alerts:evaluate"],
        )
    )
    db_session.commit()
    resp = client.post(
        "/api/v1/auth/service-token",
        json={
            "client_id": client_id,
            "client_secret": "dev-c3-secret",
            "scope": ["alerts:evaluate"],
        },
    )
    token = resp.json()["data"]["token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 403
    assert me.json()["error"]["code"] == "forbidden"
