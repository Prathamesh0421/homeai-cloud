"""Pure rules: connectivity rows (plan §4.2), S3 key layout (§2.3), media_events document (§4.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.gateways.s3_media_gateway import CONTENT_TYPES, build_key
from app.repositories.media_event_repo import new_media_event
from app.services.connectivity import derive

NOW = datetime(2026, 11, 10, 18, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("last_clip_ago", "status", "expected"),
    [
        (None, "provisioned", ("unknown", "provisioned")),
        (timedelta(seconds=10), "provisioned", ("online", "active")),
        (timedelta(seconds=30), "inactive", ("online", "active")),  # boundary: <= interval
        (timedelta(seconds=10), "error", ("online", "error")),
        (timedelta(seconds=31), "active", ("offline", "inactive")),
        (timedelta(days=2), "error", ("offline", "error")),
    ],
)
def test_derive_connectivity(last_clip_ago, status, expected):
    last = NOW - last_clip_ago if last_clip_ago is not None else None
    assert derive(last_clip_at=last, capture_interval_s=30, status=status, now=NOW) == expected


def test_s3_key_layout():
    key = build_key("t", "h", "f", "m", "wav", NOW)
    assert key == "tenants/t/houses/h/feeds/f/2026/11/10/m.wav"


def test_content_type_extensions_and_kinds():
    assert CONTENT_TYPES["audio/wav"] == ("wav", "audio")
    assert CONTENT_TYPES["audio/x-wav"] == ("wav", "audio")
    assert CONTENT_TYPES["audio/mpeg"] == ("mp3", "audio")
    assert CONTENT_TYPES["video/mp4"] == ("mp4", "video")


def _doc(client_clip_id):
    return new_media_event(
        media_id="m",
        tenant_id="t",
        house_id="h",
        room_id="r",
        feed_id="f",
        media_kind="audio",
        bucket="b",
        key="k",
        size=3,
        content_type="audio/wav",
        captured_at=NOW,
        uploaded_at=NOW,
        client_clip_id=client_clip_id,
    )


def test_media_event_document_matches_contract():
    doc = _doc("kitchen-1840")
    assert set(doc) == {
        "_id", "tenant_id", "house_id", "room_id", "feed_id", "media_kind", "s3",
        "captured_at", "uploaded_at", "client_clip_id", "status", "attempts", "claimed_at",
        "worker_id", "error", "detection_id", "handoff_status",
    }  # fmt: skip
    assert doc["s3"] == {"bucket": "b", "key": "k", "size": 3, "content_type": "audio/wav"}
    assert (doc["status"], doc["attempts"], doc["handoff_status"]) == ("queued", 0, "none")


def test_media_event_without_client_id_leaves_the_field_out():
    # The unique partial index only covers documents where client_clip_id exists.
    assert "client_clip_id" not in _doc(None)
