"""AlertViewKeyProvider with a stubbed Secrets Manager client (no AWS, no LocalStack)."""

from __future__ import annotations

import base64
import json

import boto3
import pytest
from app.gateways.secrets_gateway import AlertViewKeyProvider, parse_secret
from app.gateways.types import DependencyUnavailableError
from botocore.exceptions import EndpointConnectionError
from botocore.stub import Stubber

SECRET_ID = "homeai/alert-view-hmac"
KEY = b"k" * 32
OLD = b"o" * 32


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def sm(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    client = boto3.client("secretsmanager", region_name="us-west-2")
    with Stubber(client) as stub:
        yield client, stub
        stub.assert_no_pending_responses()


def provider(client, **kw) -> AlertViewKeyProvider:
    return AlertViewKeyProvider(secret_id=SECRET_ID, region="us-west-2", client=client, **kw)


def ok(stub, secret: str) -> None:
    stub.add_response(
        "get_secret_value",
        {"Name": SECRET_ID, "SecretString": secret},
        {"SecretId": SECRET_ID},
    )


def test_plain_base64_secret(sm):
    client, stub = sm
    ok(stub, b64(KEY))
    ring = provider(client)()
    assert (ring.current_kid, ring.keys) == ("k1", {"k1": KEY})


def test_json_secret_with_previous_key(sm):
    client, stub = sm
    ok(
        stub,
        json.dumps(
            {"current": {"kid": "k2", "key": b64(KEY)}, "previous": {"kid": "k1", "key": b64(OLD)}}
        ),
    )
    ring = provider(client)()
    assert (ring.current_kid, ring.keys) == ("k2", {"k2": KEY, "k1": OLD})


def test_cached_for_five_minutes(sm):
    client, stub = sm
    clock = Clock()
    ok(stub, b64(KEY))
    p = provider(client, clock=clock)
    p()
    clock.t = 299
    p()  # no second call (Stubber would fail on an unexpected request)
    clock.t = 301
    ok(stub, b64(OLD))
    assert p().keys == {"k1": OLD}


def test_refresh_failure_keeps_cached_keys(sm):
    client, stub = sm
    clock = Clock()
    ok(stub, b64(KEY))
    p = provider(client, clock=clock)
    p()
    clock.t = 400
    stub.add_client_error(
        "get_secret_value", service_error_code="InternalServiceError", http_status_code=500
    )
    assert p().keys == {"k1": KEY}


def test_missing_secret_in_demo_mode_uses_a_stable_in_memory_key(sm):
    client, stub = sm
    stub.add_client_error(
        "get_secret_value", service_error_code="ResourceNotFoundException", http_status_code=400
    )
    p = provider(client, demo_mode=True, ttl_s=0)
    first = p()
    stub.add_client_error(
        "get_secret_value", service_error_code="ResourceNotFoundException", http_status_code=400
    )
    assert p() is first  # links stay valid for the life of the process
    assert first.current_kid == "ephemeral" and len(first.keys["ephemeral"]) == 32


def test_missing_secret_outside_demo_mode_is_503(sm):
    client, stub = sm
    stub.add_client_error(
        "get_secret_value", service_error_code="ResourceNotFoundException", http_status_code=400
    )
    with pytest.raises(DependencyUnavailableError) as exc:
        provider(client)()
    assert (exc.value.source, "ResourceNotFoundException" in str(exc.value)) == ("secrets", True)


def test_unreachable_secrets_manager_is_503(monkeypatch):
    class Down:
        def get_secret_value(self, **_):
            raise EndpointConnectionError(endpoint_url="http://localstack:4566")

    with pytest.raises(DependencyUnavailableError, match="EndpointConnectionError"):
        provider(Down())()


def test_override_skips_secrets_manager():
    class NeverCalled:
        def get_secret_value(self, **_):
            raise AssertionError("should not call Secrets Manager")

    assert provider(NeverCalled(), override_b64=b64(KEY))().keys == {"k1": KEY}


@pytest.mark.parametrize("bad", ["not base64!", b64(b"short"), '{"current": {"kid": "k2"}}'])
def test_bad_key_material(bad, sm):
    client, stub = sm
    ok(stub, bad)
    with pytest.raises(DependencyUnavailableError):
        provider(client)()


def test_parse_secret_accepts_unpadded_base64():
    assert parse_secret(b64(KEY).rstrip("=")).keys["k1"] == KEY


def test_client_is_built_lazily_with_the_endpoint(monkeypatch):
    built = {}
    monkeypatch.setattr(
        "app.gateways.secrets_gateway.boto3.client",
        lambda service, **kw: built.update(service=service, **kw) or object(),
    )
    p = AlertViewKeyProvider(
        secret_id=SECRET_ID, region="us-west-2", endpoint_url="http://localstack:4566"
    )
    p._sm()
    assert built == {
        "service": "secretsmanager",
        "region_name": "us-west-2",
        "endpoint_url": "http://localstack:4566",
    }
