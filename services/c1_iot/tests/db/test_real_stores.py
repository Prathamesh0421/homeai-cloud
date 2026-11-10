"""Real stores end to end: LocalStack S3 + MongoDB + Postgres (plan §7: "ingest 201 → document in
Mongo + object in LocalStack S3"; "playback URL returns presigned URL").

Needs ``AWS_ENDPOINT_URL`` (LocalStack), ``MONGO_URL_C1`` and ``DATABASE_URL_C1``. Skipped locally
without them; a failure on CI.
"""

from __future__ import annotations

import os
import urllib.request
import uuid
from datetime import UTC, datetime

import pytest
from app.api.deps import get_media_repo, get_session
from app.gateways.s3_media_gateway import S3MediaGateway, StorageError
from app.main import create_app
from app.models import House
from app.repositories.media_event_repo import MediaEventRepository
from fastapi.testclient import TestClient
from homeai_common.s3 import s3_client

from tests.db.conftest import _unavailable
from tests.factories import HOUSE_A1, ROOM_A1_KITCHEN, TENANT_A, make_feed

ENDPOINT = os.environ.get("AWS_ENDPOINT_URL")
REGION = os.environ.get("AWS_REGION", "us-west-2")


@pytest.fixture(scope="module")
def bucket() -> str:
    if not ENDPOINT:
        _unavailable("AWS_ENDPOINT_URL (LocalStack) not set")
    name = f"homeai-c1-test-{uuid.uuid4().hex[:8]}"
    client = s3_client(REGION, ENDPOINT)
    try:
        client.create_bucket(Bucket=name, CreateBucketConfiguration={"LocationConstraint": REGION})
    except Exception as exc:  # pragma: no cover - environment dependent
        _unavailable(f"LocalStack unreachable: {exc}")
    yield name
    for obj in client.list_objects_v2(Bucket=name).get("Contents", []):
        client.delete_object(Bucket=name, Key=obj["Key"])
    client.delete_bucket(Bucket=name)


@pytest.fixture
def gateway(bucket) -> S3MediaGateway:
    return S3MediaGateway(bucket=bucket, region=REGION, endpoint_url=ENDPOINT)


def test_put_presign_delete(gateway):
    key = f"tenants/t/houses/h/feeds/f/2026/11/10/{uuid.uuid4()}.wav"
    gateway.put(key, b"RIFF-data", "audio/wav")
    head = gateway.client.head_object(Bucket=gateway.bucket, Key=key)
    assert head["ServerSideEncryption"] == "AES256"
    assert head["ContentType"] == "audio/wav"

    url, expires_at = gateway.presign(key, 900)
    assert "X-Amz-Expires=900" in url
    assert expires_at > datetime.now(UTC)
    with urllib.request.urlopen(url, timeout=5) as resp:
        assert resp.read() == b"RIFF-data"

    gateway.delete(key)
    assert gateway.client.list_objects_v2(Bucket=gateway.bucket, Prefix=key).get("KeyCount") == 0


def test_put_to_missing_bucket_raises_storage_error():
    if not ENDPOINT:
        _unavailable("AWS_ENDPOINT_URL (LocalStack) not set")
    broken = S3MediaGateway(bucket="no-such-bucket-c1", region=REGION, endpoint_url=ENDPOINT)
    with pytest.raises(StorageError):
        broken.put("k", b"x", "audio/wav")


def test_ingest_end_to_end(settings, seeded, gateway, auth_header):
    from tests.mongo.conftest import MONGO_URL

    if not MONGO_URL:
        _unavailable("MONGO_URL_C1 not set")
    from homeai_common.mongo import get_mongo_db

    collection = get_mongo_db(MONGO_URL)[f"media_events_e2e_{uuid.uuid4().hex[:8]}"]
    maple = seeded.get(House, HOUSE_A1)
    feed = make_feed(maple, ROOM_A1_KITCHEN, is_enabled=True)
    seeded.add(feed)
    seeded.flush()

    app = create_app(settings, checks={})
    app.state.storage = gateway
    app.dependency_overrides[get_session] = lambda: seeded
    app.dependency_overrides[get_media_repo] = lambda: MediaEventRepository(collection)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            staff = auth_header(role="iot_staff", tenant_id=TENANT_A)
            resp = client.post(
                "/api/v1/ingest/clip",
                data={
                    "feed_id": feed.feed_id,
                    "media_kind": "audio",
                    "captured_at": datetime.now(UTC).isoformat(),
                    "client_clip_id": "e2e-1",
                },
                files={"file": ("glass_break.wav", b"RIFF-e2e", "audio/wav")},
                headers=staff,
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()["data"]
            stored = collection.find_one({"_id": body["media_id"]})
            assert stored["status"] == "queued"
            assert stored["s3"]["bucket"] == gateway.bucket
            obj = gateway.client.get_object(Bucket=gateway.bucket, Key=body["s3_key"])
            assert obj["Body"].read() == b"RIFF-e2e"
    finally:
        # The app's shutdown closed the shared client; drop through a fresh one.
        get_mongo_db(MONGO_URL)[collection.name].drop()
