"""C2-04: alert types and alert rules API against Postgres (C1 houses via the fake reader)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.api.deps import get_house_reader, get_session
from app.main import create_app
from fastapi.testclient import TestClient

from tests.factories import (
    BATH,
    HOUSE_A1,
    HOUSE_A2,
    KITCHEN,
    MAPLE,
    OAK,
    OWNER_USER,
    PINE,
    ROOM_A1_BATH,
    ROOM_A1_KITCHEN,
    STAFF_USER,
    TENANT_A,
    TENANT_B,
    make_alert,
    make_rule,
    uid,
)
from tests.fakes import FakeHouseReader

RULES = "/api/v1/alert-rules"


@pytest.fixture
def houses() -> FakeHouseReader:
    return FakeHouseReader([MAPLE, OAK, PINE], [BATH, KITCHEN])


@pytest.fixture
def client(settings, session, houses):
    app = create_app(settings, checks={})
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_house_reader] = lambda: houses
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def staff(client, auth_header):
    return auth_header(user_id=STAFF_USER, role="cloud_staff", tenant_id=None)


@pytest.fixture
def owner(client, auth_header):
    return auth_header(
        user_id=OWNER_USER, role="house_owner", tenant_id=TENANT_A, house_ids=[HOUSE_A1]
    )


def fall_rule(**overrides) -> dict:
    body = {
        "house_id": HOUSE_A1,
        "alert_type_code": "fall",
        "trigger_labels": ["fall_indicator"],
        "room_id": ROOM_A1_BATH,
        "min_confidence": 0.70,
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not ...}


def issues(response) -> dict[str, str]:
    assert response.status_code == 422, response.text
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    return {d["field"]: d["issue"] for d in body["details"]}


# --- alert types ----------------------------------------------------------------------------


def test_alert_types_for_owner_and_staff(client, owner, staff):
    for headers in (owner, staff):
        r = client.get("/api/v1/alert-types", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["meta"] == {"page": 1, "page_size": 25, "total": 7}
        smoke = next(t for t in body["data"] if t["code"] == "smoke")
        assert smoke == {
            "code": "smoke",
            "name": "Smoke alarm",
            "category": "emergency",
            "service_code": "fire_safety",
            "trigger_label": "smoke_alarm",
            "default_severity": "critical",
            "default_min_confidence": 0.5,
        }
    r = client.get("/api/v1/alert-types", params={"page": 2, "page_size": 5}, headers=staff)
    assert len(r.json()["data"]) == 2


def test_alert_types_need_owner_or_staff(client, auth_header):
    assert client.get("/api/v1/alert-types").status_code == 401
    iot = auth_header(role="iot_staff", tenant_id=TENANT_A)
    r = client.get("/api/v1/alert-types", headers=iot)
    assert (r.status_code, r.json()["error"]["code"]) == (403, "forbidden")


# --- create ---------------------------------------------------------------------------------


def test_create_house_rule(client, staff):
    r = client.post(RULES, json=fall_rule(), headers=staff)
    assert r.status_code == 201, r.text
    rule = r.json()["data"]
    assert r.headers["Location"] == f"{RULES}/{rule['rule_id']}"
    assert r.headers["ETag"] == '"1"'
    assert rule | {"rule_id": None, "created_at": None, "updated_at": None} == {
        "rule_id": None,
        "tenant_id": TENANT_A,  # derived from the house
        "house_id": HOUSE_A1,
        "scope": "house",
        "alert_type_code": "fall",
        "alert_type_name": "Possible fall",
        "trigger_labels": ["fall_indicator"],
        "min_confidence": 0.7,
        "room_id": ROOM_A1_BATH,
        "severity": None,
        "effective_severity": "high",
        "is_enabled": True,
        "version": 1,
        "false_positive_count_30d": 0,
        "created_by": STAFF_USER,
        "created_at": None,
        "updated_at": None,
    }
    assert rule["created_at"].endswith("Z")
    assert client.get(r.headers["Location"], headers=staff).json()["data"] == rule


def test_create_tenant_default_uses_type_default_confidence(client, staff):
    body = {
        "tenant_id": TENANT_B,
        "alert_type_code": "smoke",
        "trigger_labels": ["smoke_alarm", "smoke_alarm"],
    }
    rule = client.post(RULES, json=body, headers=staff).json()["data"]
    assert (rule["scope"], rule["tenant_id"], rule["house_id"]) == (
        "tenant_default",
        TENANT_B,
        None,
    )
    assert rule["min_confidence"] == 0.5
    assert rule["trigger_labels"] == ["smoke_alarm"]  # de-duplicated
    assert rule["effective_severity"] == "critical"


def test_duplicate_rule_is_409(client, staff):
    assert client.post(RULES, json=fall_rule(), headers=staff).status_code == 201
    r = client.post(RULES, json=fall_rule(min_confidence=0.8), headers=staff)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "duplicate_rule")
    # A disabled copy is allowed.
    assert client.post(RULES, json=fall_rule(is_enabled=False), headers=staff).status_code == 201


@pytest.mark.parametrize(
    ("overrides", "field", "issue"),
    [
        ({"alert_type_code": "earthquake"}, "alert_type_code", "unknown alert type"),
        ({"trigger_labels": ["thunder"]}, "trigger_labels.0", "Input should be"),
        ({"trigger_labels": []}, "trigger_labels", "at least 1"),
        ({"min_confidence": 1.5}, "min_confidence", "less than or equal to 1"),
        ({"min_confidence": 0.555}, "min_confidence", "2 decimal places"),
        ({"severity": "urgent"}, "severity", "Input should be"),
        ({"house_id": "not-a-uuid"}, "house_id", "UUID"),
        ({"house_id": uid()}, "house_id", "unknown house"),
        ({"tenant_id": TENANT_B}, "tenant_id", "does not match"),
        ({"room_id": ROOM_A1_KITCHEN, "house_id": HOUSE_A2}, "room_id", "does not belong"),
        ({"room_id": uid()}, "room_id", "does not belong"),
        ({"house_id": ..., "tenant_id": TENANT_A}, "room_id", "needs a house_id"),
        ({"house_id": ..., "room_id": ...}, "tenant_id", "required when house_id"),
        ({"owner": "me"}, "owner", "Extra inputs"),
    ],
)
def test_create_validation(client, staff, overrides, field, issue):
    got = issues(client.post(RULES, json=fall_rule(**overrides), headers=staff))
    assert field in got, got
    assert issue in got[field]


def test_create_returns_503_when_c1_is_down(client, staff, houses):
    houses.down = True
    r = client.post(RULES, json=fall_rule(), headers=staff)
    assert r.status_code == 503
    assert r.json()["error"] == {
        "code": "dependency_unavailable",
        "message": "c1 is unavailable",
        "details": {"source": "c1"},
    }


def test_reader_not_configured_is_503(settings, session, staff, auth_header):
    # No dependency override for the house reader and no DATABASE_READER_URL_C2.
    app = create_app(settings, checks={})
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        headers = auth_header(user_id=STAFF_USER, role="cloud_staff")
        r = c.post(RULES, json=fall_rule(), headers=headers)
    assert (r.status_code, r.json()["error"]["details"]) == (503, {"source": "c2_reader"})


# --- access ---------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["house_owner", "iot_staff"])
def test_rules_are_cloud_staff_only(client, auth_header, session, role):
    rule = make_rule(session, "fall", house_id=HOUSE_A1)
    headers = auth_header(role=role, tenant_id=TENANT_A, house_ids=[HOUSE_A1])
    for method, path, body in [
        ("GET", RULES, None),
        ("GET", f"{RULES}/{rule.rule_id}", None),
        ("POST", RULES, fall_rule()),
        ("POST", f"{RULES}/defaults", {"tenant_id": TENANT_A}),
        ("DELETE", f"{RULES}/{rule.rule_id}", None),
    ]:
        r = client.request(method, path, json=body, headers=headers)
        assert r.status_code == 403, (method, path)
    assert client.get(RULES).status_code == 401
    service = auth_header(service_scopes=["alerts:evaluate"])
    assert client.get(RULES, headers=service).status_code == 403


# --- list and get ---------------------------------------------------------------------------


def test_list_filters_and_false_positive_counts(client, staff, session):
    fall = make_rule(session, "fall", house_id=HOUSE_A1)
    make_rule(session, "smoke")
    make_rule(session, "pet", house_id=HOUSE_A2, is_enabled=False)
    make_rule(session, "smoke", tenant_id=TENANT_B)
    make_alert(
        session, fall, status="false_positive", triggered_at=datetime.now(UTC) - timedelta(days=2)
    )

    r = client.get(RULES, params={"tenant_id": TENANT_A}, headers=staff)
    assert r.json()["meta"]["total"] == 3
    counts = {x["alert_type_code"]: x["false_positive_count_30d"] for x in r.json()["data"]}
    assert counts == {"fall": 1, "smoke": 0, "pet": 0}

    def total(**params):
        return client.get(RULES, params=params, headers=staff).json()["meta"]["total"]

    assert total() == 4  # cloud staff see every tenant
    assert total(tenant_id=TENANT_A, house_id=HOUSE_A1) == 1
    assert total(tenant_id=TENANT_A, alert_type_code="smoke") == 1
    assert total(is_enabled="false") == 1
    assert client.get(RULES, params={"page_size": 1}, headers=staff).json()["meta"] == {
        "page": 1,
        "page_size": 1,
        "total": 4,
    }
    assert (
        client.get(f"{RULES}/{fall.rule_id}", headers=staff).json()["data"][
            "false_positive_count_30d"
        ]
        == 1
    )


def test_get_unknown_or_bad_id(client, staff):
    r = client.get(f"{RULES}/{uid()}", headers=staff)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")
    assert issues(client.get(f"{RULES}/nope", headers=staff)) == {
        "rule_id": "Value error, must be a UUID"
    }


# --- update ---------------------------------------------------------------------------------


def _create(client, staff, **overrides) -> dict:
    r = client.post(RULES, json=fall_rule(**overrides), headers=staff)
    assert r.status_code == 201, r.text
    return r.json()["data"]


def test_update_with_if_match(client, staff):
    rule = _create(client, staff, severity="critical")
    url = f"{RULES}/{rule['rule_id']}"
    r = client.put(
        url, json={"min_confidence": 0.75, "severity": None}, headers={**staff, "If-Match": '"1"'}
    )
    assert r.status_code == 200, r.text
    assert r.headers["ETag"] == '"2"'
    got = r.json()["data"]
    assert (got["version"], got["min_confidence"], got["severity"]) == (2, 0.75, None)
    assert got["effective_severity"] == "high"
    assert got["room_id"] == ROOM_A1_BATH  # untouched

    # Weak and unquoted forms are accepted too.
    assert (
        client.put(
            url, json={"is_enabled": False}, headers={**staff, "If-Match": 'W/"2"'}
        ).status_code
        == 200
    )
    assert (
        client.put(url, json={"room_id": None}, headers={**staff, "If-Match": "3"}).json()["data"][
            "room_id"
        ]
        is None
    )


def test_stale_version_is_412_with_current_version(client, staff):
    rule = _create(client, staff)
    url = f"{RULES}/{rule['rule_id']}"
    assert (
        client.put(
            url, json={"min_confidence": 0.8}, headers={**staff, "If-Match": '"1"'}
        ).status_code
        == 200
    )
    r = client.put(url, json={"min_confidence": 0.9}, headers={**staff, "If-Match": '"1"'})
    assert r.status_code == 412
    assert r.json()["error"]["code"] == "version_mismatch"
    assert r.json()["error"]["details"] == {"current_version": 2}


@pytest.mark.parametrize(
    ("body", "if_match", "field"),
    [
        ({"min_confidence": 0.8}, None, "If-Match"),
        ({"min_confidence": 0.8}, "latest", "If-Match"),
        ({}, '"1"', "body"),
        ({"min_confidence": None}, '"1"', "min_confidence"),
        ({"trigger_labels": None}, '"1"', "trigger_labels"),
        ({"room_id": "33333333-0000-0000-0000-00000000a1ff"}, '"1"', "room_id"),
        ({"tenant_id": TENANT_B}, '"1"', "tenant_id"),
    ],
)
def test_update_validation(client, staff, body, if_match, field):
    rule = _create(client, staff)
    headers = dict(staff)
    if if_match is not None:
        headers["If-Match"] = if_match
    got = issues(client.put(f"{RULES}/{rule['rule_id']}", json=body, headers=headers))
    assert any(f.lower() == field.lower() for f in got), got


def test_update_room_must_stay_in_the_house(client, staff):
    rule = _create(client, staff)
    url = f"{RULES}/{rule['rule_id']}"
    ok = client.put(url, json={"room_id": ROOM_A1_KITCHEN}, headers={**staff, "If-Match": '"1"'})
    assert ok.json()["data"]["room_id"] == ROOM_A1_KITCHEN
    default = client.post(
        RULES,
        json={"tenant_id": TENANT_A, "alert_type_code": "pet", "trigger_labels": ["dog"]},
        headers=staff,
    ).json()["data"]
    got = issues(
        client.put(
            f"{RULES}/{default['rule_id']}",
            json={"room_id": ROOM_A1_BATH},
            headers={**staff, "If-Match": '"1"'},
        )
    )
    assert "needs a house_id" in got["room_id"]


def test_reenabling_into_a_duplicate_is_409(client, staff):
    _create(client, staff)
    disabled = _create(client, staff, is_enabled=False)
    r = client.put(
        f"{RULES}/{disabled['rule_id']}",
        json={"is_enabled": True},
        headers={**staff, "If-Match": '"1"'},
    )
    assert (r.status_code, r.json()["error"]["code"]) == (409, "duplicate_rule")


def test_update_unknown_rule_is_404(client, staff):
    r = client.put(
        f"{RULES}/{uid()}", json={"is_enabled": False}, headers={**staff, "If-Match": '"1"'}
    )
    assert r.status_code == 404


# --- delete ---------------------------------------------------------------------------------


def test_delete_is_soft_and_then_404(client, staff, session):
    rule = _create(client, staff)
    url = f"{RULES}/{rule['rule_id']}"
    r = client.delete(url, headers=staff)
    assert (r.status_code, r.content) == (204, b"")
    assert client.get(url, headers=staff).status_code == 404
    assert client.delete(url, headers=staff).status_code == 404
    assert client.get(RULES, headers=staff).json()["meta"]["total"] == 0
    # A new rule for the same slot is allowed after deletion.
    assert client.post(RULES, json=fall_rule(), headers=staff).status_code == 201


# --- tenant defaults ------------------------------------------------------------------------


def test_create_defaults_is_idempotent_per_tenant(client, staff):
    url = f"{RULES}/defaults"
    r = client.post(url, json={"tenant_id": TENANT_A}, headers=staff)
    assert (r.status_code, r.json()) == (200, {"data": {"created": 7}})
    assert client.post(url, json={"tenant_id": TENANT_A}, headers=staff).json() == {
        "data": {"created": 0}
    }
    assert client.post(url, json={"tenant_id": TENANT_B}, headers=staff).json() == {
        "data": {"created": 7}
    }

    rules = client.get(RULES, params={"tenant_id": TENANT_A}, headers=staff).json()["data"]
    assert {r["scope"] for r in rules} == {"tenant_default"}
    by_type = {r["alert_type_code"]: (r["trigger_labels"], r["min_confidence"]) for r in rules}
    assert by_type["intrusion"] == (["glass_break"], 0.55)
    assert by_type["fall"] == (["fall_indicator"], 0.65)


def test_create_defaults_requires_tenant(client, staff):
    assert "tenant_id" in issues(client.post(f"{RULES}/defaults", json={}, headers=staff))


def test_openapi_lists_rule_routes(client):
    paths = client.get("/api/v1/docs/c2/openapi.json").json()["paths"]
    assert {"/api/v1/alert-types", RULES, f"{RULES}/defaults", f"{RULES}/{{rule_id}}"} <= set(paths)


def test_real_reader_wiring_reads_c1(settings, session, auth_header):
    # Real C1HouseGateway over its own reader connection: C1's tables exist (its migration ran
    # in pg_engine), but that connection cannot see this test's uncommitted rows, so C1 answers
    # "no such house". A 422 (not 503 c1) proves the reader reached c1.houses.
    from tests.db.conftest import DATABASE_URL

    app = create_app(settings.model_copy(update={"database_reader_url": DATABASE_URL}), checks={})
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        headers = auth_header(user_id=STAFF_USER, role="cloud_staff")
        r = c.post(RULES, json=fall_rule(), headers=headers)
    assert issues(r) == {"house_id": "unknown house"}


def test_create_defaults_skips_a_default_created_concurrently(client, staff, session, monkeypatch):
    from app.repositories.alert_type_repo import AlertTypeRepository
    from app.repositories.rule_repo import RuleRepository

    make_rule(session, "smoke")  # appears between "what is missing" and the insert
    every_type = AlertTypeRepository(session).list_all()
    monkeypatch.setattr(RuleRepository, "types_missing_default", lambda self, tenant_id: every_type)
    r = client.post(f"{RULES}/defaults", json={"tenant_id": TENANT_A}, headers=staff)
    assert r.json() == {"data": {"created": 6}}
