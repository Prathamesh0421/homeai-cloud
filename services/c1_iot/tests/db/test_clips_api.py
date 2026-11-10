"""C1-07: Clip Library list/detail/playback against Postgres names and a fake media_events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.models import House
from app.repositories.media_event_repo import new_media_event

from tests.factories import (
    HOUSE_A1,
    HOUSE_A2,
    HOUSE_B1,
    ROOM_A1_KITCHEN,
    ROOM_B1_KITCHEN,
    TENANT_A,
    TENANT_B,
    make_feed,
    make_room,
    uid,
)

CLIPS = "/api/v1/clips"
T0 = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def add_clip(media, feed, minutes: int, status="queued") -> str:
    media_id = uid()
    doc = new_media_event(
        media_id=media_id,
        tenant_id=feed.tenant_id,
        house_id=feed.house_id,
        room_id=feed.room_id,
        feed_id=feed.feed_id,
        media_kind=feed.media_kind,
        bucket="homeai-c1-test",
        key=f"tenants/{feed.tenant_id}/houses/{feed.house_id}/feeds/{feed.feed_id}/{media_id}.wav",
        size=1000 + minutes,
        content_type="audio/wav",
        captured_at=T0 + timedelta(minutes=minutes),
        uploaded_at=T0 + timedelta(minutes=minutes, seconds=2),
        client_clip_id=None,
    )
    doc["status"] = status
    media.docs[media_id] = doc
    return media_id


@pytest.fixture
def clips(seeded, media):
    maple = seeded.get(House, HOUSE_A1)
    oak = seeded.get(House, HOUSE_A2)
    pine = seeded.get(House, HOUSE_B1)
    oak_room = make_room(HOUSE_A2, name="Den")
    seeded.add(oak_room)
    seeded.flush()
    kitchen = make_feed(maple, ROOM_A1_KITCHEN, name="Kitchen Mic", is_enabled=True)
    oak_mic = make_feed(oak, oak_room.room_id, name="Oak Mic", is_enabled=True)
    pine_mic = make_feed(pine, ROOM_B1_KITCHEN, name="Pine Mic", is_enabled=True)
    seeded.add_all([kitchen, oak_mic, pine_mic])
    seeded.flush()
    return {
        "maple_old": add_clip(media, kitchen, 1, status="analyzed"),
        "maple_new": add_clip(media, kitchen, 5),
        "oak": add_clip(media, oak_mic, 3),
        "pine": add_clip(media, pine_mic, 4),
        "kitchen": kitchen,
    }


def ids(resp) -> list[str]:
    return [c["media_id"] for c in resp.json()["data"]]


def test_staff_lists_tenant_clips_newest_first_with_names(api, staff, clips):
    resp = api.get(CLIPS, headers=staff)
    assert resp.status_code == 200
    assert ids(resp) == [clips["maple_new"], clips["oak"], clips["maple_old"]]
    first = resp.json()["data"][0]
    assert (first["feed_name"], first["room_name"]) == ("Kitchen Mic", "Kitchen")
    assert first["captured_at"] == "2026-11-10T12:05:00Z"
    assert resp.json()["meta"]["total"] == 3


def test_filters(api, staff, clips):
    assert ids(api.get(CLIPS, params={"status": "analyzed"}, headers=staff)) == [clips["maple_old"]]
    assert ids(api.get(CLIPS, params={"house_id": HOUSE_A2}, headers=staff)) == [clips["oak"]]
    feed_id = clips["kitchen"].feed_id
    assert len(ids(api.get(CLIPS, params={"feed_id": feed_id}, headers=staff))) == 2
    window = {"from": "2026-11-10T12:02:00Z", "to": "2026-11-10T12:04:00Z"}
    assert ids(api.get(CLIPS, params=window, headers=staff)) == [clips["oak"]]


def test_owner_sees_only_own_house(api, owner, clips):
    assert ids(api.get(CLIPS, headers=owner)) == [clips["maple_new"], clips["maple_old"]]
    assert ids(api.get(CLIPS, params={"house_id": HOUSE_A2}, headers=owner)) == []
    assert api.get(f"{CLIPS}/{clips['oak']}", headers=owner).status_code == 404


def test_cloud_staff_tenant_filter(api, ops, clips):
    assert len(ids(api.get(CLIPS, headers=ops))) == 4
    assert ids(api.get(CLIPS, params={"tenant_id": TENANT_B}, headers=ops)) == [clips["pine"]]


def test_detail_with_top_label(api, staff, clips, detections):
    detections.docs.append(
        {"media_id": clips["maple_old"], "top_label": "glass_break", "top_confidence": 0.78}
    )
    body = api.get(f"{CLIPS}/{clips['maple_old']}", headers=staff).json()["data"]
    assert (body["top_label"], body["top_confidence"]) == ("glass_break", 0.78)
    assert body["tenant_id"] == TENANT_A
    assert body["content_type"] == "audio/wav"
    listed = api.get(CLIPS, params={"status": "analyzed"}, headers=staff).json()["data"][0]
    assert listed["top_label"] == "glass_break"


def test_other_tenant_clip_is_404(api, staff_b, clips):
    assert api.get(f"{CLIPS}/{clips['maple_new']}", headers=staff_b).status_code == 404
    assert api.get(f"{CLIPS}/{clips['maple_new']}/playback-url", headers=staff_b).status_code == 404


def test_playback_url_for_users_and_c2_service(api, staff, owner, auth_header, clips):
    resp = api.get(f"{CLIPS}/{clips['maple_new']}/playback-url", headers=owner)
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "X-Amz-Expires=900" in body["url"]
    assert body["expires_at"].endswith("Z")
    c2 = auth_header(service_scopes=["clips:playback"])
    assert api.get(f"{CLIPS}/{clips['pine']}/playback-url", headers=c2).status_code == 200
    no_scope = auth_header(service_scopes=["feeds:read"])
    assert api.get(f"{CLIPS}/{clips['pine']}/playback-url", headers=no_scope).status_code == 403


def test_playback_url_storage_failure_is_503(api, staff, clips, storage):
    storage.fail_presign = True
    resp = api.get(f"{CLIPS}/{clips['maple_new']}/playback-url", headers=staff)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "storage_unavailable"


def test_feed_detail_lists_last_clips(api, staff, clips):
    body = api.get(f"/api/v1/feeds/{clips['kitchen'].feed_id}", headers=staff).json()["data"]
    assert [c["media_id"] for c in body["recent_clips"]] == [clips["maple_new"], clips["maple_old"]]
