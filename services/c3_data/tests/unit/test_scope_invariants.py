"""C3-10 hardening (unit): JWT-claim contract, unscoped-filter invariant, house_in_scope.

4.2 pins C3's reading of the token to the library that writes it (homeai_common.testing mints
tokens the way C4 does). 4.3 proves only cross-tenant roles ever get an unscoped (tenant=None)
scope. These are Tier 1 / Tier 3-contract: no infra, but 4.2 is pinned to the real token writer.
"""

from __future__ import annotations

import pytest
from app.services.record_scope import RecordScope, house_in_scope, record_scope
from homeai_common import auth
from homeai_common.auth import JwksCache
from homeai_common.testing import make_test_keys, mint_service_token, mint_user_token


@pytest.fixture
def principal_from_token(monkeypatch):
    """Verify a minted token through homeai_common.auth exactly as the service does."""
    private, _pub, entry = make_test_keys(kid="test-key")

    class _StaticJwks(JwksCache):
        def __init__(self):
            super().__init__(jwks_url="static")
            self._keys = {entry["kid"]: entry}
            self._fetched_at = 1e12

        def _refresh(self):
            pass

    monkeypatch.setattr(auth, "_default_cache", _StaticJwks())

    def _make(*, service_scopes=None, **claims):
        if service_scopes is not None:
            token = mint_service_token(private, kid="test-key", scopes=service_scopes)
        else:
            token = mint_user_token(private, kid="test-key", **claims)
        return auth.verify_token(token)

    return _make


# -- 4.2 JWT claim contract: record_scope reads the real token shape per role ---------------
def test_scope_house_owner_with_houses(principal_from_token):
    p = principal_from_token(role="house_owner", tenant_id="A", house_ids=["h1", "h2"])
    s = record_scope(p, tenant_id="IGNORED")
    assert s == RecordScope(tenant_id="A", house_ids=("h1", "h2"))


def test_scope_house_owner_with_no_houses(principal_from_token):
    p = principal_from_token(role="house_owner", tenant_id="A", house_ids=[])
    s = record_scope(p)
    assert s.tenant_id == "A"
    assert s.house_ids == ()  # sees nothing, not everything


def test_scope_iot_staff(principal_from_token):
    p = principal_from_token(role="iot_staff", tenant_id="A")
    assert record_scope(p) == RecordScope(tenant_id="A", house_ids=None)


def test_scope_cloud_staff(principal_from_token):
    p = principal_from_token(role="cloud_staff", tenant_id="A")
    assert record_scope(p).tenant_id is None
    assert record_scope(p, tenant_id="B").tenant_id == "B"


def test_scope_service_with_records_read(principal_from_token):
    p = principal_from_token(service_scopes=["records:read"])
    assert record_scope(p, tenant_id="B").tenant_id == "B"


# -- 4.3 unscoped-filter invariant ----------------------------------------------------------
def test_only_cross_tenant_roles_get_unscoped(principal_from_token):
    # Every non-cross-tenant principal must carry a concrete tenant_id (never None).
    for role, tenant in (("house_owner", "A"), ("iot_staff", "A")):
        p = principal_from_token(role=role, tenant_id=tenant, house_ids=["h1"])
        assert record_scope(p).tenant_id is not None, f"{role} must be tenant-scoped"


# -- house_in_scope shared helper -----------------------------------------------------------
def test_house_in_scope_allows_within_scope():
    assert house_in_scope(RecordScope(tenant_id="A", house_ids=("h1",)), "h1") == (True, "h1")


def test_house_in_scope_blocks_out_of_scope():
    assert house_in_scope(RecordScope(tenant_id="A", house_ids=("h1",)), "oak") == (False, None)


def test_house_in_scope_no_explicit_house():
    assert house_in_scope(RecordScope(tenant_id=None), None) == (True, None)


def test_house_in_scope_cloud_any_house():
    # cloud_staff (house_ids=None) may target any house explicitly.
    assert house_in_scope(RecordScope(tenant_id=None), "any") == (True, "any")
