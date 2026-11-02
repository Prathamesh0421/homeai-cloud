"""Unit tests for homeai_common.auth token verification."""

from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest
from homeai_common import auth
from homeai_common.auth import JwksCache, Principal, verify_token
from homeai_common.testing import make_test_keys, mint_service_token, mint_user_token


class _StaticJwks(JwksCache):
    def __init__(self, entry):
        super().__init__(jwks_url="static")
        self._keys = {entry["kid"]: entry}
        self._fetched_at = 1e12

    def _refresh(self):
        pass


@pytest.fixture
def keys():
    private, _public, entry = make_test_keys(kid="test-key")
    auth._default_cache = _StaticJwks(entry)
    return private


def test_verify_user_token_builds_principal(keys):
    token = mint_user_token(
        keys, kid="test-key", user_id="u1", role="house_owner", tenant_id="t1", house_ids=["h1"]
    )
    principal = verify_token(token)
    assert principal.is_user
    assert principal.sub == "u1"
    assert principal.role == "house_owner"
    assert principal.tenant_id == "t1"
    assert principal.house_ids == ("h1",)


def test_verify_service_token_builds_principal(keys):
    token = mint_service_token(
        keys, kid="test-key", client_id="c3-worker", scopes=["alerts:evaluate"]
    )
    principal = verify_token(token)
    assert principal.is_service
    assert principal.sub == "c3-worker"
    assert principal.has_scope("alerts:evaluate")
    assert not principal.has_scope("feeds:read")


def test_expired_token_returns_token_expired(keys):
    token = mint_user_token(keys, kid="test-key", ttl_seconds=-120)
    with pytest.raises(Exception) as exc:
        verify_token(token)
    # FastAPI HTTPException carries detail dict
    detail = exc.value.detail
    assert detail["code"] == "token_expired"


def test_wrong_audience_rejected(keys):
    now = int(time.time())
    payload = {
        "iss": auth.ISSUER,
        "aud": "someone-else",
        "typ": "user",
        "sub": "u1",
        "role": "house_owner",
        "tenant_id": "t1",
        "house_ids": [],
        "email": "x@y",
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + 60,
    }
    token = jwt.encode(payload, keys, algorithm="RS256", headers={"kid": "test-key"})
    with pytest.raises(Exception) as exc:
        verify_token(token)
    assert exc.value.detail["code"] == "unauthorized"


def test_unknown_kid_rejected(keys):
    other = make_test_keys(kid="other-key")[0]
    token = mint_user_token(other, kid="other-key")
    with pytest.raises(Exception) as exc:
        verify_token(token)
    assert exc.value.detail["code"] == "unauthorized"


def test_revoked_jti_rejected(keys):
    jti = str(uuid4())
    token = mint_user_token(keys, kid="test-key", jti=jti)
    principal = verify_token(token, revoked_jtis=set())
    assert principal.jti == jti
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        verify_token(token, revoked_jtis={jti})
    assert exc.value.detail["code"] == "token_revoked"


def test_require_roles_dependency(keys):
    from fastapi import HTTPException

    token = mint_user_token(keys, kid="test-key", role="house_owner")
    verify_token(token)
    dep = auth.require_roles("cloud_staff")
    # Simulate FastAPI calling the dependency function with the principal.
    with pytest.raises(HTTPException):
        dep(principal=Principal(kind="user", sub="u", role="house_owner", tenant_id="t"))


def test_assert_house_owner_allowed():
    from fastapi import HTTPException

    principal = Principal(
        kind="user", sub="u", role="house_owner", tenant_id="t", house_ids=("h1",)
    )
    auth.assert_house(principal, "h1")  # no raise
    with pytest.raises(HTTPException):
        auth.assert_house(principal, "h2")


def test_assert_house_cloud_staff_bypasses():
    principal = Principal(kind="user", sub="u", role="cloud_staff", tenant_id="t")
    auth.assert_house(principal, "any-house")  # no raise


def test_tenant_filter_scopes_non_cloud():
    principal = Principal(kind="user", sub="u", role="house_owner", tenant_id="t1")
    assert auth.tenant_filter(principal) == "t1"
    cs = Principal(kind="user", sub="u", role="cloud_staff", tenant_id="t1")
    assert auth.tenant_filter(cs) is None
