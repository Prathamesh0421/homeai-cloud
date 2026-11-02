"""Unit tests for the JWT issuer and JWKS output."""

import jwt
from app.services.jwt_issuer import JwtIssuer, landing_for_role
from app.settings import Settings


def _make_issuer() -> JwtIssuer:
    from app.services.jwt_issuer import generate_signing_key

    key = generate_signing_key("test-key")
    settings = Settings(env="test", jwt_private_key_pem=key.private_pem, jwt_kid="test-key")
    return JwtIssuer(settings=settings, key=key, previous=None)


def test_user_token_has_required_claims():
    issuer = _make_issuer()
    token, jti, ttl = issuer.issue_user_token(
        user_id="11111111-1111-1111-1111-111111111111",
        role="house_owner",
        tenant_id="22222222-2222-2222-2222-222222222222",
        house_ids=["33333333-3333-3333-3333-333333333333"],
        email="owner@acme.test",
    )
    assert ttl == 3600
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["iss"] == "homeai-c4"
    assert claims["aud"] == "homeai"
    assert claims["typ"] == "user"
    assert claims["role"] == "house_owner"
    assert claims["email"] == "owner@acme.test"
    assert claims["jti"] == jti


def test_service_token_has_scope_claim():
    issuer = _make_issuer()
    token, _jti, ttl = issuer.issue_service_token(client_id="c3-worker", scopes=["alerts:evaluate"])
    assert ttl == 900
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["typ"] == "service"
    assert claims["sub"] == "c3-worker"
    assert claims["scope"] == ["alerts:evaluate"]


def test_jwks_publishes_current_key():
    issuer = _make_issuer()
    jwks = issuer.jwks()
    assert len(jwks["keys"]) == 1
    entry = jwks["keys"][0]
    assert entry["kty"] == "RSA"
    assert entry["kid"] == "test-key"
    assert entry["alg"] == "RS256"
    assert "n" in entry and "e" in entry


def test_landing_for_role():
    assert landing_for_role("house_owner") == "/home/overview"
    assert landing_for_role("iot_staff") == "/iot/feeds"
    assert landing_for_role("cloud_staff") == "/ops/dashboard"
    assert landing_for_role("unknown") == "/login"
