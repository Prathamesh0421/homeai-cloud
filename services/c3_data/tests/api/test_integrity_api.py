"""C3-12: integrity endpoints — authz and validation (no stores needed).

The store-backed run is covered by the integration tests; here we pin the operator-only
access (cloud_staff) and the uuid validation, which are enforced before any store access.
"""

from __future__ import annotations

import uuid

import pytest
from app.api import integrity as integrity_api
from app.api.deps import get_session
from homeai_common.errors import ApiError


@pytest.fixture
def client(make_client):
    c = make_client()
    app = c.app
    # Stub the write session so role/validation checks (not a store error) are what we exercise.
    app.dependency_overrides[get_session] = lambda: object()
    yield c
    app.dependency_overrides.clear()


def test_run_check_forbidden_for_iot_staff(client, auth_header):
    r = client.post(
        "/api/v1/integrity-checks",
        headers=auth_header(role="iot_staff", tenant_id="t1"),
    )
    assert r.status_code == 403


def test_run_check_forbidden_for_house_owner(client, auth_header):
    r = client.post(
        "/api/v1/integrity-checks",
        headers=auth_header(role="house_owner", tenant_id="t1", house_ids=["h1"]),
    )
    assert r.status_code == 403


def test_list_forbidden_for_house_owner(client, auth_header):
    r = client.get(
        "/api/v1/integrity-reports",
        headers=auth_header(role="house_owner", tenant_id="t1"),
    )
    assert r.status_code == 403


def test_run_check_bad_tenant_id_is_422(client, auth_header):
    r = client.post(
        "/api/v1/integrity-checks?tenant_id=not-a-uuid",
        headers=auth_header(role="cloud_staff"),
    )
    assert r.status_code == 422


def test_get_report_bad_id_is_422(client, auth_header):
    r = client.get(
        "/api/v1/integrity-reports/not-a-uuid",
        headers=auth_header(role="cloud_staff"),
    )
    assert r.status_code == 422


def test_require_uuid_accepts_valid_and_rejects_invalid():
    integrity_api._require_uuid(str(uuid.uuid4()), "tenant_id")  # no raise
    with pytest.raises(ApiError):
        integrity_api._require_uuid("nope", "tenant_id")
