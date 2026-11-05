"""API tests: tenants + users admin (C4-07)."""

from __future__ import annotations

from uuid import uuid4

import bcrypt
from app.models.orm import Tenant, User
from sqlalchemy.orm import Session

from tests.conftest import skip_no_postgres


def _seed_cs(db_session: Session, email: str = "ops@homeai.test") -> User:
    tenant = Tenant(name=f"homeai-{uuid4()}", timezone="UTC")
    db_session.add(tenant)
    db_session.flush()
    user = User(
        tenant_id=tenant.tenant_id,
        email=email,
        password_hash=bcrypt.hashpw(b"Demo!2026", bcrypt.gensalt()).decode(),
        role="cloud_staff",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _seed_owner(db_session: Session, email: str = "owner@acme.test") -> User:
    tenant = Tenant(name=f"acme-{uuid4()}", timezone="UTC")
    db_session.add(tenant)
    db_session.flush()
    user = User(
        tenant_id=tenant.tenant_id,
        email=email,
        password_hash=bcrypt.hashpw(b"Demo!2026", bcrypt.gensalt()).decode(),
        role="house_owner",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _login(client, email: str) -> str:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "Demo!2026"})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@skip_no_postgres
def test_tenants_users_403_for_house_owner(client, db_session):
    _seed_owner(db_session)
    db_session.commit()
    token = _login(client, "owner@acme.test")
    resp = client.get("/api/v1/tenants", headers=_auth(token))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"
    resp = client.post(
        "/api/v1/tenants", headers=_auth(token), json={"name": "x", "timezone": "UTC"}
    )
    assert resp.status_code == 403


@skip_no_postgres
def test_tenants_list_cs(client, db_session):
    _seed_cs(db_session)
    db_session.commit()
    token = _login(client, "ops@homeai.test")
    resp = client.get("/api/v1/tenants", headers=_auth(token))
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


@skip_no_postgres
def test_create_tenant_then_create_user(client, db_session, monkeypatch):
    _seed_cs(db_session)
    db_session.commit()
    token = _login(client, "ops@homeai.test")

    # mock the best-effort C2 call
    calls: list = []
    import app.services.tenant_user_service as svc

    def _fake_post(url, *, json, headers, timeout):
        class _R:
            status_code = 204
            text = ""

        calls.append((url, json))
        return _R()

    monkeypatch.setattr(svc.httpx, "post", _fake_post)

    resp = client.post(
        "/api/v1/tenants", headers=_auth(token), json={"name": "Acme", "timezone": "UTC"}
    )
    assert resp.status_code == 201, resp.text
    tenant_id = resp.json()["data"]["tenant_id"]
    assert calls and calls[0][1]["tenant_id"] == tenant_id

    # create a user with a valid password
    resp = client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        headers=_auth(token),
        json={
            "email": "owner.maple@acme.test",
            "password": "Demo!2026abc",
            "role": "house_owner",
            "house_ids": [],
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["email"] == "owner.maple@acme.test"
    assert "password_hash" not in data
    assert data["is_active"] is True

    # list users
    resp = client.get(f"/api/v1/tenants/{tenant_id}/users", headers=_auth(token))
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


@skip_no_postgres
def test_create_user_bad_password_422(client, db_session):
    _seed_cs(db_session)
    db_session.commit()
    token = _login(client, "ops@homeai.test")
    resp = client.post(
        "/api/v1/tenants", headers=_auth(token), json={"name": "Acme2", "timezone": "UTC"}
    )
    tenant_id = resp.json()["data"]["tenant_id"]
    # too short
    resp = client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        headers=_auth(token),
        json={"email": "x@y.test", "password": "abc123", "role": "house_owner"},
    )
    assert resp.status_code == 422
    # no digits
    resp = client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        headers=_auth(token),
        json={"email": "x@y.test", "password": "abcdefghij", "role": "house_owner"},
    )
    assert resp.status_code == 422
    # no letters
    resp = client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        headers=_auth(token),
        json={"email": "x@y.test", "password": "1234567890", "role": "house_owner"},
    )
    assert resp.status_code == 422


@skip_no_postgres
def test_create_user_bad_house_id_422(client, db_session):
    _seed_cs(db_session)
    db_session.commit()
    token = _login(client, "ops@homeai.test")
    resp = client.post(
        "/api/v1/tenants", headers=_auth(token), json={"name": "Acme3", "timezone": "UTC"}
    )
    tenant_id = resp.json()["data"]["tenant_id"]
    resp = client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        headers=_auth(token),
        json={
            "email": "x@y.test",
            "password": "Demo!2026ab",
            "role": "house_owner",
            "house_ids": ["not-a-uuid"],
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "bad_house_id"


@skip_no_postgres
def test_create_tenant_duplicate_409(client, db_session):
    _seed_cs(db_session)
    db_session.commit()
    token = _login(client, "ops@homeai.test")
    client.post("/api/v1/tenants", headers=_auth(token), json={"name": "Dup", "timezone": "UTC"})
    resp = client.post(
        "/api/v1/tenants", headers=_auth(token), json={"name": "Dup", "timezone": "UTC"}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "tenant_exists"


@skip_no_postgres
def test_patch_user_unlock_and_password(client, db_session):
    _seed_cs(db_session)
    db_session.commit()
    token = _login(client, "ops@homeai.test")
    # create tenant + user
    t = client.post(
        "/api/v1/tenants", headers=_auth(token), json={"name": "Acme4", "timezone": "UTC"}
    ).json()["data"]["tenant_id"]
    u = client.post(
        f"/api/v1/tenants/{t}/users",
        headers=_auth(token),
        json={"email": "u@y.test", "password": "Demo!2026ab", "role": "iot_staff"},
    ).json()["data"]
    uid = u["user_id"]

    # patch role + unlock
    resp = client.patch(
        f"/api/v1/users/{uid}", headers=_auth(token), json={"role": "cloud_staff", "unlock": True}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["role"] == "cloud_staff"

    # patch password
    resp = client.patch(
        f"/api/v1/users/{uid}", headers=_auth(token), json={"password": "NewPass1234"}
    )
    assert resp.status_code == 200
    # login with new password
    login = client.post("/api/v1/auth/login", json={"email": "u@y.test", "password": "NewPass1234"})
    assert login.status_code == 200


@skip_no_postgres
def test_patch_user_never_returns_hash(client, db_session):
    _seed_cs(db_session)
    db_session.commit()
    token = _login(client, "ops@homeai.test")
    t = client.post(
        "/api/v1/tenants", headers=_auth(token), json={"name": "Acme5", "timezone": "UTC"}
    ).json()["data"]["tenant_id"]
    u = client.post(
        f"/api/v1/tenants/{t}/users",
        headers=_auth(token),
        json={"email": "u2@y.test", "password": "Demo!2026ab", "role": "iot_staff"},
    ).json()["data"]
    resp = client.patch(
        f"/api/v1/users/{u['user_id']}", headers=_auth(token), json={"is_active": False}
    )
    body = resp.json()["data"]
    assert "password_hash" not in body
    assert body["is_active"] is False


@skip_no_postgres
def test_create_tenant_c2_failure_still_201(client, db_session, monkeypatch):
    _seed_cs(db_session)
    db_session.commit()
    token = _login(client, "ops@homeai.test")
    import app.services.tenant_user_service as svc

    def _fail(url, *, json, headers, timeout):
        raise RuntimeError("c2 down")

    monkeypatch.setattr(svc.httpx, "post", _fail)
    resp = client.post(
        "/api/v1/tenants", headers=_auth(token), json={"name": "Acme6", "timezone": "UTC"}
    )
    assert resp.status_code == 201
