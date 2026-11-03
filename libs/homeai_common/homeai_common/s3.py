"""S3 client and presigned GET URLs (contracts §5.3).

Locally ``AWS_ENDPOINT_URL=http://localstack:4566`` is only reachable from inside compose.
A presigned URL embeds (and signs) its host, so URLs handed to a browser must be signed
against a browser-reachable endpoint: pass ``public_endpoint_url`` (``AWS_PUBLIC_ENDPOINT_URL``,
e.g. ``http://localhost:4566``). On AWS both are unset and boto3 uses the real S3 endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from botocore.config import Config

DEFAULT_PRESIGN_TTL_SECONDS = 15 * 60


def s3_client(region: str, endpoint_url: str | None = None, **kwargs: Any) -> Any:
    """boto3 S3 client; path-style + SigV4 so LocalStack and presigning behave like AWS."""
    config = Config(signature_version="s3v4", s3={"addressing_style": "path"})
    return boto3.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint_url or None,
        config=config,
        **kwargs,
    )


def presign_get(
    bucket: str,
    key: str,
    ttl_seconds: int = DEFAULT_PRESIGN_TTL_SECONDS,
    *,
    region: str,
    endpoint_url: str | None = None,
    public_endpoint_url: str | None = None,
    client: Any | None = None,
) -> tuple[str, datetime]:
    """Return ``(url, expires_at)`` for a time-limited GET of ``s3://bucket/key``.

    ``public_endpoint_url`` (if set) wins over ``endpoint_url`` because the URL is for a browser.
    ``expires_at`` is UTC; serialise it through a Pydantic model to get the ``Z`` suffix.
    """
    signer = client or s3_client(region, public_endpoint_url or endpoint_url)
    url = signer.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=ttl_seconds
    )
    expires_at = (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).replace(microsecond=0)
    return url, expires_at
