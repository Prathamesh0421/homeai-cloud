"""API tests: settings + emergency contacts (C4-06)."""

from __future__ import annotations

from uuid import uuid4

import bcrypt
from app.models.orm import Tenant, User
from sqlalchemy.orm import Session

from tests.conftest import skip_no_postgres


def _seed_user(
    db_session: Session,
    *,
    email: str,
    role: str = "house_owner",
    password: str = "Demo!2026",
    house_ids: list | None = None,
    is_active: bool = True,
) -> tuple[Tenant, User]:
    tenant = Tenant(name=f"t-{uuid4()}", timezone="UTC")
    db_session.add(tenant)
    db_session.flush()
    user = User(
        tenant_id=tenant.tenant_id,
        email=email,
        password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        role=role,
        house_ids=house_ids or [],
        is_active=is_active,
    )
    db_session.add(user)
    db_session.flush()
    return tenant, user


def _login_token(client, email: str, password: str = "Demo!2026") -> str:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- Settings ---


@skip_no_postgres
def test_get_settings_returns_defaults_when_no_row(client, db_session):
    house_id = uuid4()
    _seed_user(db_session, email="owner@acme.test", house_ids=[house_id])
    db_session.commit()
    token = _login_token(client, "owner@acme.test")
    resp = client.get(f"/api/v1/houses/{house_id}/settings", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["is_default"] is True
    assert data["enabled_services"] == [
        "fire_safety",
        "distress",
        "intrusion",
        "fall",
        "wellness",
        "presence",
        "pet",
    ]
    assert data["quiet_start"] is None
    assert data["quiet_end"] is None
    assert data["sensitivity"] == "medium"


@skip_no_postgres
def test_put_settings_upserts_and_persists(client, db_session):
    house_id = uuid4()
    _seed_user(db_session, email="owner@acme.test", house_ids=[house_id])
    db_session.commit()
    token = _login_token(client, "owner@acme.test")
    body = {
        "enabled_services": ["fire_safety", "intrusion"],
        "quiet_start": "22:00",
        "quiet_end": "06:00",
        "sensitivity": "high",
    }
    resp = client.put(f"/api/v1/houses/{house_id}/settings", headers=_auth(token), json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["is_default"] is False
    assert data["sensitivity"] == "high"
    assert data["quiet_start"] == "22:00"
    resp2 = client.get(f"/api/v1/houses/{house_id}/settings", headers=_auth(token))
    assert resp2.json()["data"]["enabled_services"] == ["fire_safety", "intrusion"]


@skip_no_postgres
def test_put_settings_422_one_quiet_time(client, db_session):
    house_id = uuid4()
    _seed_user(db_session, email="owner@acme.test", house_ids=[house_id])
    db_session.commit()
    token = _login_token(client, "owner@acme.test")
    body = {"enabled_services": ["fire_safety"], "quiet_start": "22:00", "quiet_end": None}
    resp = client.put(f"/api/v1/houses/{house_id}/settings", headers=_auth(token), json=body)
    assert resp.status_code == 422


@skip_no_postgres
def test_put_settings_422_bad_time_format(client, db_session):
    house_id = uuid4()
    _seed_user(db_session, email="owner@acme.test", house_ids=[house_id])
    db_session.commit()
    token = _login_token(client, "owner@acme.test")
    body = {"enabled_services": ["fire_safety"], "quiet_start": "25:00", "quiet_end": "06:00"}
    resp = client.put(f"/api/v1/houses/{house_id}/settings", headers=_auth(token), json=body)
    assert resp.status_code == 422


@skip_no_postgres
def test_put_settings_422_unknown_service(client, db_session):
    house_id = uuid4()
    _seed_user(db_session, email="owner@acme.test", house_ids=[house_id])
    db_session.commit()
    token = _login_token(client, "owner@acme.test")
    body = {"enabled_services": ["fire_safety", "not_a_service"]}
    resp = client.put(f"/api/v1/houses/{house_id}/settings", headers=_auth(token), json=body)
    assert resp.status_code == 422


@skip_no_postgres
def test_settings_owner_403_on_other_house(client, db_session):
    own_house = uuid4()
    other_house = uuid4()
    _seed_user(db_session, email="owner@acme.test", house_ids=[own_house])
    db_session.commit()
    token = _login_token(client, "owner@acme.test")
    resp = client.get(f"/api/v1/houses/{other_house}/settings", headers=_auth(token))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


@skip_no_postgres
def test_settings_cloud_staff_can_access_any_house(client, db_session):
    house_id = uuid4()
    _seed_user(db_session, email="ops@homeai.test", role="cloud_staff")
    db_session.commit()
    token = _login_token(client, "ops@homeai.test")
    resp = client.get(f"/api/v1/houses/{house_id}/settings", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["is_default"] is True


# --- Emergency contacts ---


@skip_no_postgres
def test_contact_crud_and_priority(client, db_session):
    house_id = uuid4()
    _seed_user(db_session, email="owner@acme.test", house_ids=[house_id])
    db_session.commit()
    token = _login_token(client, "owner@acme.test")
    ids = []
    for i, name in enumerate(["Alice", "Bob", "Carol"], start=1):
        resp = client.post(
            f"/api/v1/houses/{house_id}/emergency-contacts",
            headers=_auth(token),
            json={"name": name, "email": f"{name.lower()}@x.test", "contact_type": "family"},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["priority"] == i
        ids.append(data["contact_id"])
    resp = client.get(f"/api/v1/houses/{house_id}/emergency-contacts", headers=_auth(token))
    assert [c["name"] for c in resp.json()["data"]] == ["Alice", "Bob", "Carol"]
    resp = client.patch(
        f"/api/v1/emergency-contacts/{ids[1]}",
        headers=_auth(token),
        json={"phone": "555-1234"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["phone"] == "555-1234"
    resp = client.delete(f"/api/v1/emergency-contacts/{ids[0]}", headers=_auth(token))
    assert resp.status_code == 204
    items = client.get(
        f"/api/v1/houses/{house_id}/emergency-contacts", headers=_auth(token)
    ).json()["data"]
    assert [c["priority"] for c in items] == [1, 2]
    assert [c["name"] for c in items] == ["Bob", "Carol"]


@skip_no_postgres
def test_contact_limit_409(client, db_session):
    house_id = uuid4()
    _seed_user(db_session, email="owner@acme.test", house_ids=[house_id])
    db_session.commit()
    token = _login_token(client, "owner@acme.test")
    for i in range(5):
        client.post(
            f"/api/v1/houses/{house_id}/emergency-contacts",
            headers=_auth(token),
            json={"name": f"C{i}", "email": f"c{i}@x.test", "contact_type": "neighbor"},
        )
    resp = client.post(
        f"/api/v1/houses/{house_id}/emergency-contacts",
        headers=_auth(token),
        json={"name": "C6", "email": "c6@x.test", "contact_type": "neighbor"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "contact_limit"


@skip_no_postgres
def test_contact_email_exists_409(client, db_session):
    house_id = uuid4()
    _seed_user(db_session, email="owner@acme.test", house_ids=[house_id])
    db_session.commit()
    token = _login_token(client, "owner@acme.test")
    client.post(
        f"/api/v1/houses/{house_id}/emergency-contacts",
        headers=_auth(token),
        json={"name": "Alice", "email": "dup@x.test", "contact_type": "family"},
    )
    resp = client.post(
        f"/api/v1/houses/{house_id}/emergency-contacts",
        headers=_auth(token),
        json={"name": "Bob", "email": "dup@x.test", "contact_type": "family"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "email_exists"


@skip_no_postgres
def test_contact_reorder_422_missing_id(client, db_session):
    house_id = uuid4()
    _seed_user(db_session, email="owner@acme.test", house_ids=[house_id])
    db_session.commit()
    token = _login_token(client, "owner@acme.test")
    r1 = client.post(
        f"/api/v1/houses/{house_id}/emergency-contacts",
        headers=_auth(token),
        json={"name": "A", "email": "a@x.test", "contact_type": "family"},
    ).json()["data"]
    client.post(
        f"/api/v1/houses/{house_id}/emergency-contacts",
        headers=_auth(token),
        json={"name": "B", "email": "b@x.test", "contact_type": "family"},
    )
    resp = client.put(
        f"/api/v1/houses/{house_id}/emergency-contacts/order",
        headers=_auth(token),
        json={"contact_ids": [r1["contact_id"]]},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "reorder_mismatch"


@skip_no_postgres
def test_contact_reorder_success(client, db_session):
    house_id = uuid4()
    _seed_user(db_session, email="owner@acme.test", house_ids=[house_id])
    db_session.commit()
    token = _login_token(client, "owner@acme.test")
    r1 = client.post(
        f"/api/v1/houses/{house_id}/emergency-contacts",
        headers=_auth(token),
        json={"name": "A", "email": "a@x.test", "contact_type": "family"},
    ).json()["data"]
    r2 = client.post(
        f"/api/v1/houses/{house_id}/emergency-contacts",
        headers=_auth(token),
        json={"name": "B", "email": "b@x.test", "contact_type": "family"},
    ).json()["data"]
    r3 = client.post(
        f"/api/v1/houses/{house_id}/emergency-contacts",
        headers=_auth(token),
        json={"name": "C", "email": "c@x.test", "contact_type": "family"},
    ).json()["data"]
    resp = client.put(
        f"/api/v1/houses/{house_id}/emergency-contacts/order",
        headers=_auth(token),
        json={"contact_ids": [r3["contact_id"], r2["contact_id"], r1["contact_id"]]},
    )
    assert resp.status_code == 204
    items = client.get(
        f"/api/v1/houses/{house_id}/emergency-contacts", headers=_auth(token)
    ).json()["data"]
    assert [c["name"] for c in items] == ["C", "B", "A"]
    assert [c["priority"] for c in items] == [1, 2, 3]


@skip_no_postgres
def test_contact_insert_at_existing_priority_shifts(client, db_session):
    house_id = uuid4()
    _seed_user(db_session, email="owner@acme.test", house_ids=[house_id])
    db_session.commit()
    token = _login_token(client, "owner@acme.test")
    client.post(
        f"/api/v1/houses/{house_id}/emergency-contacts",
        headers=_auth(token),
        json={"name": "A", "email": "a@x.test", "contact_type": "family"},
    )
    client.post(
        f"/api/v1/houses/{house_id}/emergency-contacts",
        headers=_auth(token),
        json={"name": "B", "email": "b@x.test", "contact_type": "family"},
    )
    c = client.post(
        f"/api/v1/houses/{house_id}/emergency-contacts",
        headers=_auth(token),
        json={"name": "C", "email": "c@x.test", "contact_type": "family", "priority": 1},
    ).json()["data"]
    assert c["priority"] == 1
    items = client.get(
        f"/api/v1/houses/{house_id}/emergency-contacts", headers=_auth(token)
    ).json()["data"]
    assert [x["name"] for x in items] == ["C", "A", "B"]


@skip_no_postgres
def test_contacts_owner_403_on_other_house(client, db_session):
    own = uuid4()
    other = uuid4()
    _seed_user(db_session, email="owner@acme.test", house_ids=[own])
    db_session.commit()
    token = _login_token(client, "owner@acme.test")
    resp = client.get(f"/api/v1/houses/{other}/emergency-contacts", headers=_auth(token))
    assert resp.status_code == 403
