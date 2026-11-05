"""Tests for the C4 seed module (C4-15)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import time

import bcrypt
import pytest
from app.models.orm import EmergencyContact, HouseServiceSetting, ServiceClient, Tenant, User
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine

from tests.conftest import skip_no_postgres
from tests.db.conftest import owner_url

# docs/02_CONTRACTS.md §2.3: the scope each client calls with, and the secret it sends
# (.env.example / LocalStack homeai/service-clients).
CONTRACT = {
    "c2-alerts": (["clips:playback"], "dev-c2-secret"),
    "c3-worker": (["alerts:evaluate"], "dev-c3-secret"),
    "c3-data": (["alerts:evaluate"], "dev-c3-secret"),
    "c4-dashboard": (["feeds:read", "alerts:read", "records:read"], "dev-c4-secret"),
    "device-uploader": (["ingest:write"], "dev-device-secret"),
}
SECRET_ENV = (
    "SERVICE_CLIENT_SECRET_C2",
    "SERVICE_CLIENT_SECRET_C3",
    "SERVICE_CLIENT_SECRET_C4",
    "SERVICE_CLIENT_SECRET_DEVICE",
)


@pytest.fixture(autouse=True)
def dev_secrets(monkeypatch):
    for var in SECRET_ENV:  # the dev defaults, whatever the shell exports
        monkeypatch.delenv(var, raising=False)


@skip_no_postgres
def test_seed_creates_all_rows(db_session):
    import app.seed as seed_mod

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

    # docs/03 §7: Maple all on, quiet 22:00-07:00, medium; Oak wellness off, high.
    settings = list(db_session.scalars(select(HouseServiceSetting)))
    assert len(settings) == 2
    maple = next(s for s in settings if str(s.house_id).endswith("0000a1"))
    assert (maple.quiet_start, maple.quiet_end, maple.sensitivity) == (
        time(22, 0),
        time(7, 0),
        "medium",
    )
    assert len(maple.enabled_services) == 7
    oak = next(s for s in settings if str(s.house_id).endswith("0000a2"))
    assert (oak.quiet_start, oak.sensitivity) == (None, "high")
    assert "wellness" not in oak.enabled_services and len(oak.enabled_services) == 6

    contacts = list(db_session.scalars(select(EmergencyContact)))
    assert len(contacts) == 3
    assert {c.priority for c in contacts} == {1, 2, 3}

    clients = {c.client_id: c for c in db_session.scalars(select(ServiceClient))}
    assert {cid: c.scopes for cid, c in clients.items()} == {
        cid: scopes for cid, (scopes, _) in CONTRACT.items()
    }
    for cid, (_, secret) in CONTRACT.items():
        assert bcrypt.checkpw(secret.encode(), clients[cid].secret_hash.encode()), cid


@skip_no_postgres
def test_secrets_follow_the_env(db_session, monkeypatch):
    import app.seed as seed_mod

    monkeypatch.setenv("SERVICE_CLIENT_SECRET_C3", "rotated-c3")
    seed_mod.run()
    worker = db_session.get(ServiceClient, "c3-worker")
    db_session.refresh(worker)
    assert bcrypt.checkpw(b"rotated-c3", worker.secret_hash.encode())


@skip_no_postgres
def test_seed_login_and_service_token(client, db_session):
    """DoD: login as owner.maple@acme.test / Demo!2026, and every client gets its token."""
    import app.seed as seed_mod

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

    # Each service client gets a token for the scope it calls with (C3 -> C2 handoff, etc.).
    for client_id, (scopes, secret) in CONTRACT.items():
        resp = client.post(
            "/api/v1/auth/service-token",
            json={"client_id": client_id, "client_secret": secret, "scope": scopes},
        )
        assert resp.status_code == 200, (client_id, resp.text)
        assert "token" in resp.json()["data"]

    # ...and nothing beyond it.
    resp = client.post(
        "/api/v1/auth/service-token",
        json={
            "client_id": "c3-worker",
            "client_secret": "dev-c3-secret",
            "scope": ["clips:playback"],
        },
    )
    assert resp.status_code >= 400


# --- as compose runs it: migrations, then the seed, both as c4_app ------------------------------


@pytest.fixture
def seeded_as_owner(migrated) -> Iterator[Engine]:
    import app.db.session as session_mod

    engine = create_engine(owner_url())
    saved = session_mod._engine, session_mod._SessionFactory
    session_mod._engine, session_mod._SessionFactory = engine, None
    try:
        yield engine
    finally:
        session_mod._engine, session_mod._SessionFactory = saved
        engine.dispose()
        with migrated.connect() as conn:  # 0003's downgrade needs users.tenant_id filled
            conn.execute(
                text(
                    "TRUNCATE c4.emergency_contacts, c4.house_service_settings, c4.users, "
                    "c4.service_clients, c4.tenants CASCADE"
                )
            )


@skip_no_postgres
def test_seed_runs_as_c4_app_after_the_migrations(seeded_as_owner, migrated):
    import app.seed as seed_mod

    assert seed_mod.run()["service_clients"] == 5
    with migrated.connect() as conn:
        owners = set(
            conn.execute(text("SELECT tableowner FROM pg_tables WHERE schemaname = 'c4'")).scalars()
        )
        contacts = conn.execute(text("SELECT count(*) FROM c4.emergency_contacts")).scalar()
        c2_reads = conn.execute(
            text("SELECT has_table_privilege('c2_reader', 'c4.emergency_contacts', 'SELECT')")
        ).scalar()
    assert owners == {"c4_app"}  # nothing created outside the migrations
    assert (contacts, c2_reads) == (3, True)


def test_seed_refuses_without_the_migrations(monkeypatch):
    import app.db.session as session_mod
    import app.seed as seed_mod

    monkeypatch.setattr(session_mod, "get_engine", lambda: create_engine("sqlite://"))
    with pytest.raises(SystemExit, match="run the C4 migrations first"):
        seed_mod.run()
