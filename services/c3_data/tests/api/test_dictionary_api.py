"""C3-13: data-dictionary endpoints — authz and the reader-absent 503 (no stores)."""

from __future__ import annotations

import pytest
from app.api.deps import get_session


@pytest.fixture
def client(make_client):
    c = make_client()
    app = c.app
    # Stub the write session; the reader stays absent (default settings have no reader URL).
    app.dependency_overrides[get_session] = lambda: object()
    yield c
    app.dependency_overrides.clear()


def test_post_forbidden_for_iot_staff(client, auth_header):
    r = client.post(
        "/api/v1/data-dictionary",
        json={"version": "1.0.0", "generate": True},
        headers=auth_header(role="iot_staff", tenant_id="t1"),
    )
    assert r.status_code == 403


def test_post_forbidden_for_house_owner(client, auth_header):
    r = client.post(
        "/api/v1/data-dictionary",
        json={"version": "1.0.0", "generate": True},
        headers=auth_header(role="house_owner", tenant_id="t1", house_ids=["h1"]),
    )
    assert r.status_code == 403


def test_get_forbidden_for_iot_staff(client, auth_header):
    r = client.get("/api/v1/data-dictionary", headers=auth_header(role="iot_staff", tenant_id="t1"))
    assert r.status_code == 403


def test_post_requires_generate_or_document(client, auth_header):
    # Neither generate nor document -> request-model validation 422.
    r = client.post(
        "/api/v1/data-dictionary",
        json={"version": "1.0.0"},
        headers=auth_header(role="cloud_staff"),
    )
    assert r.status_code == 422
