"""Tests for the C4 seed module (C4-15)."""

from __future__ import annotations

from app.models.orm import EmergencyContact, HouseServiceSetting, ServiceClient, Tenant, User
from sqlalchemy import select

from tests.conftest import skip_no_postgres


@skip_no_postgres
def test_seed_creates_all_rows(db_session):
    import app.seed as seed_mod

    seed_mod._ensure_schema()
    seed_mod.run()
    seed_mod.run()  # idempotent re-run

    tenants = list(db_session.scalars(select(Tenant)))
    assert {t.name for t in tenants} == {"Acme Care", "Sunrise Living"}

    users = list(db_session.scalars(select(User)))
    emails = {u.email for u in users}
    assert "ops@homeai.test" in emails
    assert "owner.maple@acme.test" in emails
    # cloud_staff has no tenant
    ops = next(u for u in users if u.email == "ops@homeai.test")
    assert ops.tenant_id is None
    assert ops.role == "cloud_staff"
    # owner.maple owns the maple house
    owner = next(u for u in users if u.email == "owner.maple@acme.test")
    assert owner.role == "house_owner"
    assert any(str(h) == "22222222-0000-0000-0000-0000000000a1" for h in owner.house_ids)

    settings = list(db_session.scalars(select(HouseServiceSetting)))
    assert len(settings) == 2
    maple = next(s for s in settings if str(s.house_id).endswith("0000a1"))
    assert maple.quiet_start is not None
    assert maple.sensitivity == "medium"

    contacts = list(db_session.scalars(select(EmergencyContact)))
    assert len(contacts) == 3
    assert {c.priority for c in contacts} == {1, 2, 3}

    clients = list(db_session.scalars(select(ServiceClient)))
    assert {c.client_id for c in clients} == {
        "c2-alerts",
        "c3-worker",
        "c3-data",
        "c4-dashboard",
        "device-uploader",
    }
    # c4-dashboard has the documented scopes
    c4 = next(c for c in clients if c.client_id == "c4-dashboard")
    assert "users:read" in c4.scopes


@skip_no_postgres
def test_seed_login_and_service_token(client, db_session):
    """DoD: login as owner.maple@acme.test / Demo!2026 and service-token for c4-dashboard."""
    import app.seed as seed_mod

    seed_mod._ensure_schema()
    seed_mod.run()

    # user login
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "owner.maple@acme.test", "password": "Demo!2026"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["data"]["token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["data"]["user"]["role"] == "house_owner"

    # cloud staff login
    resp = client.post(
        "/api/v1/auth/login", json={"email": "ops@homeai.test", "password": "Demo!2026"}
    )
    assert resp.status_code == 200
    cs_token = resp.json()["data"]["token"]
    # cloud staff can list tenants
    resp = client.get("/api/v1/tenants", headers={"Authorization": f"Bearer {cs_token}"})
    assert resp.status_code == 200
    assert len(resp.json()["data"]) >= 2

    # service token for c4-dashboard
    resp = client.post(
        "/api/v1/auth/service-token",
        json={
            "client_id": "c4-dashboard",
            "client_secret": "dev-c4-dashboard-secret",
            "scope": ["users:read"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert "token" in resp.json()["data"]
