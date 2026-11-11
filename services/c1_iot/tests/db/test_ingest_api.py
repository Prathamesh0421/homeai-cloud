"""C1-06: POST /ingest/clip — the §4.1 decision table, in order, with fake S3 and Mongo."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.models import CameraFeed, House

from tests.factories import (
    HOUSE_A1,
    HOUSE_B1,
    ROOM_A1_KITCHEN,
    ROOM_B1_KITCHEN,
    TENANT_A,
    make_feed,
)

INGEST = "/api/v1/ingest/clip"
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64


@pytest.fixture
def feed(seeded) -> CameraFeed:
    maple = seeded.get(House, HOUSE_A1)
    f = make_feed(maple, ROOM_A1_KITCHEN, name="Kitchen Mic", is_enabled=True)
    seeded.add(f)
    seeded.flush()
    return f


def upload(api, headers, feed_id, *, kind="audio", content_type="audio/wav", data=WAV, **form):
    fields = {
        "feed_id": feed_id,
        "media_kind": kind,
        "captured_at": form.pop("captured_at", datetime.now(UTC).isoformat()),
        **form,
    }
    files = {"file": ("clip.bin", data, content_type)}
    return api.post(INGEST, data=fields, files=files, headers=headers)


def reload(seeded, feed) -> CameraFeed:
    seeded.expire_all()
    return seeded.get(CameraFeed, feed.feed_id)


def test_upload_stores_object_and_queued_record(api, staff, feed, seeded, storage, media):
    resp = upload(api, staff, feed.feed_id, client_clip_id="kitchen-1840")
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert (body["status"], body["duplicate"]) == ("queued", False)
    prefix = f"tenants/{TENANT_A}/houses/{HOUSE_A1}/feeds/{feed.feed_id}/"
    assert body["s3_key"].startswith(prefix)
    assert body["s3_key"].endswith(f"/{body['media_id']}.wav")
    assert storage.objects[body["s3_key"]] == (WAV, "audio/wav")

    doc = media.docs[body["media_id"]]
    assert (doc["status"], doc["attempts"], doc["handoff_status"]) == ("queued", 0, "none")
    assert (doc["room_id"], doc["client_clip_id"]) == (ROOM_A1_KITCHEN, "kitchen-1840")
    assert doc["s3"]["size"] == len(WAV)

    f = reload(seeded, feed)
    assert (f.status, f.connectivity_status, f.consecutive_failures) == ("active", "online", 0)
    assert f.last_clip_at is not None


def test_duplicate_client_clip_id_returns_existing(api, staff, feed, storage):
    first = upload(api, staff, feed.feed_id, client_clip_id="c-1").json()["data"]
    again = upload(api, staff, feed.feed_id, client_clip_id="c-1")
    assert again.status_code == 200
    assert again.json()["data"] == {**first, "duplicate": True}
    assert len(storage.objects) == 1


def test_without_client_id_every_upload_is_new(api, staff, feed, media):
    upload(api, staff, feed.feed_id)
    upload(api, staff, feed.feed_id)
    assert len(media.docs) == 2


def test_unknown_archived_or_other_tenant_feed_is_404(api, staff, staff_b, feed, seeded):
    assert upload(api, staff_b, feed.feed_id).status_code == 404
    assert upload(api, staff, "11111111-2222-3333-4444-555555555555").status_code == 404
    feed.archived_at = datetime.now(UTC)
    seeded.flush()
    assert upload(api, staff, feed.feed_id).json()["error"]["code"] == "not_found"


def test_disabled_feed_is_409(api, staff, feed, seeded):
    feed.is_enabled = False
    seeded.flush()
    resp = upload(api, staff, feed.feed_id)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "feed_not_enabled"


def test_kind_mismatch_is_422(api, staff, feed, storage):
    resp = upload(api, staff, feed.feed_id, kind="video", content_type="video/mp4")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "media_kind_mismatch"
    # An mp4 file sent to an audio feed as "audio" is caught too (demo step 6).
    resp = upload(api, staff, feed.feed_id, kind="audio", content_type="video/mp4")
    assert resp.json()["error"]["code"] == "media_kind_mismatch"
    assert storage.objects == {}


def test_unsupported_type_and_future_time_are_422(api, staff, feed):
    resp = upload(api, staff, feed.feed_id, content_type="image/png")
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["field"] == "file"
    future = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    resp = upload(api, staff, feed.feed_id, captured_at=future)
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["field"] == "captured_at"
    # Within the 5-minute tolerance is fine (device clocks drift).
    near = (datetime.now(UTC) + timedelta(minutes=2)).isoformat()
    assert upload(api, staff, feed.feed_id, captured_at=near).status_code == 201


def test_oversize_is_413(api, staff, feed, settings):
    settings.max_upload_bytes = 32
    resp = upload(api, staff, feed.feed_id, data=b"x" * 33)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "payload_too_large"


def test_service_token_uploads_to_any_tenant(api, auth_header, seeded):
    pine = seeded.get(House, HOUSE_B1)
    f = make_feed(pine, ROOM_B1_KITCHEN, is_enabled=True)
    seeded.add(f)
    seeded.flush()
    device = auth_header(service_scopes=["ingest:write"])
    assert upload(api, device, f.feed_id).status_code == 201
    other = auth_header(service_scopes=["feeds:read"])
    assert upload(api, other, f.feed_id).status_code == 403


def test_owner_cannot_upload(api, owner, feed):
    assert upload(api, owner, feed.feed_id).status_code == 403


def test_s3_failure_is_503_and_counts_until_error(api, staff, feed, seeded, storage, media):
    storage.fail_put = True
    for expected in (1, 2):
        resp = upload(api, staff, feed.feed_id)
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "storage_unavailable"
        f = reload(seeded, feed)
        assert (f.consecutive_failures, f.status) == (expected, "provisioned")
    upload(api, staff, feed.feed_id)
    assert reload(seeded, feed).status == "error"
    assert media.docs == {}


def test_mongo_failure_removes_the_s3_object(api, staff, feed, seeded, storage, media):
    media.fail_insert = True
    resp = upload(api, staff, feed.feed_id)
    assert resp.status_code == 503
    assert storage.objects == {}  # compensation: no orphan object
    assert reload(seeded, feed).consecutive_failures == 1


def test_success_resets_failures(api, staff, feed, seeded):
    feed.consecutive_failures = 2
    seeded.flush()
    assert upload(api, staff, feed.feed_id).status_code == 201
    assert reload(seeded, feed).consecutive_failures == 0
