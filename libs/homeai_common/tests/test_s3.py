"""S3 client config and presigned URLs (signing is offline; fake credentials only)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from homeai_common import s3


@pytest.fixture(autouse=True)
def fake_aws(monkeypatch, tmp_path):
    # Never let boto3 pick up a developer's real ~/.aws credentials in tests.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "none"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "none"))
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    # boto3 reads these itself when no endpoint is passed (CI sets AWS_ENDPOINT_URL).
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL_S3", raising=False)


def test_client_uses_endpoint_path_style_and_sigv4():
    client = s3.s3_client("us-west-2", "http://localstack:4566")
    assert client.meta.endpoint_url == "http://localstack:4566"
    assert client.meta.config.signature_version == "s3v4"
    assert client.meta.config.s3["addressing_style"] == "path"


def test_empty_endpoint_means_real_aws():
    client = s3.s3_client("us-west-2", "")
    assert "amazonaws.com" in client.meta.endpoint_url


def test_presign_uses_public_endpoint_and_ttl():
    before = datetime.now(UTC)
    url, expires_at = s3.presign_get(
        "homeai-local",
        "tenants/t/houses/h/feeds/f/2026/10/31/m.wav",
        ttl_seconds=900,
        region="us-west-2",
        endpoint_url="http://localstack:4566",
        public_endpoint_url="http://localhost:4566",
    )
    parsed = urlparse(url)
    assert parsed.netloc == "localhost:4566"
    assert parsed.path == "/homeai-local/tenants/t/houses/h/feeds/f/2026/10/31/m.wav"
    query = parse_qs(parsed.query)
    assert query["X-Amz-Expires"] == ["900"]
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert expires_at.tzinfo is UTC
    assert before + timedelta(seconds=899) <= expires_at <= before + timedelta(seconds=901)


def test_presign_falls_back_to_internal_endpoint():
    url, _ = s3.presign_get("b", "k", region="us-west-2", endpoint_url="http://localstack:4566")
    assert urlparse(url).netloc == "localstack:4566"
    assert parse_qs(urlparse(url).query)["X-Amz-Expires"] == [str(s3.DEFAULT_PRESIGN_TTL_SECONDS)]


def test_presign_with_given_client():
    client = s3.s3_client("us-west-2", "http://example:9000")
    url, _ = s3.presign_get("b", "k", 60, region="ignored", client=client)
    assert urlparse(url).netloc == "example:9000"
