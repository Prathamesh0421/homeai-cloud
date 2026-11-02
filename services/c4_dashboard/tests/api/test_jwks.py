"""API test: JWKS endpoint."""

from tests.conftest import skip_no_postgres


@skip_no_postgres
def test_jwks_returns_test_key(client):
    resp = client.get("/.well-known/jwks.json")
    assert resp.status_code == 200
    body = resp.json()
    assert "keys" in body
    assert len(body["keys"]) == 1
    entry = body["keys"][0]
    assert entry["kty"] == "RSA"
    assert entry["kid"] == "test-key"
    assert entry["alg"] == "RS256"
