"""Clip objects in S3 (contract 02 §5.3; C1 plan §2.3).

Key: ``tenants/{tenant}/houses/{house}/feeds/{feed}/{yyyy}/{mm}/{dd}/{media_id}.{ext}``, written
with SSE-S3 (AES256). Locally boto3 talks to LocalStack (``AWS_ENDPOINT_URL``); presigned URLs are
signed against ``AWS_PUBLIC_ENDPOINT_URL`` so a browser can reach them. On AWS both are unset.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from homeai_common.s3 import presign_get, s3_client

# Allowed upload content types -> (file extension, media kind).
CONTENT_TYPES: dict[str, tuple[str, str]] = {
    "audio/wav": ("wav", "audio"),
    "audio/x-wav": ("wav", "audio"),
    "audio/wave": ("wav", "audio"),
    "audio/mpeg": ("mp3", "audio"),
    "video/mp4": ("mp4", "video"),
}


class StorageError(Exception):
    """S3 could not store, delete or sign an object."""


def build_key(
    tenant_id: str, house_id: str, feed_id: str, media_id: str, ext: str, when: datetime
) -> str:
    return f"tenants/{tenant_id}/houses/{house_id}/feeds/{feed_id}/{when:%Y/%m/%d}/{media_id}.{ext}"


class MediaStorage(Protocol):
    bucket: str

    def put(self, key: str, body: bytes, content_type: str) -> None: ...

    def delete(self, key: str) -> None: ...

    def presign(self, key: str, ttl_seconds: int) -> tuple[str, datetime]: ...


class S3MediaGateway:
    """``MediaStorage`` over boto3. The client is created lazily (startup needs no network)."""

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None = None,
        public_endpoint_url: str | None = None,
        client: Any | None = None,
    ):
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url
        self.public_endpoint_url = public_endpoint_url
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = s3_client(self.region, self.endpoint_url)
        return self._client

    def put(self, key: str, body: bytes, content_type: str) -> None:
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
        except Exception as exc:
            raise StorageError(f"put_object failed: {exc}") from exc

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise StorageError(f"delete_object failed: {exc}") from exc

    def presign(self, key: str, ttl_seconds: int) -> tuple[str, datetime]:
        try:
            return presign_get(
                self.bucket,
                key,
                ttl_seconds,
                region=self.region,
                endpoint_url=self.endpoint_url,
                public_endpoint_url=self.public_endpoint_url,
            )
        except Exception as exc:
            raise StorageError(f"presign failed: {exc}") from exc
