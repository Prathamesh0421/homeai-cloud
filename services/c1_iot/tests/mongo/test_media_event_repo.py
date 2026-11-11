"""``media_events`` against a real MongoDB: indexes, exactly-once client ids, listing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.db.mongo_indexes import ensure_indexes
from app.repositories.media_event_repo import (
    DuplicateKeyError,
    MediaEventRepository,
    new_media_event,
)

T0 = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def doc(media_id: str, *, feed_id="f1", house_id="h1", client_clip_id=None, minutes=0):
    return new_media_event(
        media_id=media_id,
        tenant_id="t1",
        house_id=house_id,
        room_id="r1",
        feed_id=feed_id,
        media_kind="audio",
        bucket="b",
        key=f"k/{media_id}.wav",
        size=10,
        content_type="audio/wav",
        captured_at=T0 + timedelta(minutes=minutes),
        uploaded_at=T0 + timedelta(minutes=minutes),
        client_clip_id=client_clip_id,
    )


@pytest.fixture
def repo(collection) -> MediaEventRepository:
    ensure_indexes(collection)
    return MediaEventRepository(collection)


def test_indexes_match_contract(collection):
    ensure_indexes(collection)
    ensure_indexes(collection)  # idempotent
    info = collection.index_information()
    keys = {tuple(i["key"]) for i in info.values()}
    assert (("status", 1), ("uploaded_at", 1)) in keys
    assert (("house_id", 1), ("captured_at", -1)) in keys
    unique = next(
        i for i in info.values() if tuple(i["key"]) == (("feed_id", 1), ("client_clip_id", 1))
    )
    assert unique["unique"] is True
    assert unique["partialFilterExpression"] == {"client_clip_id": {"$exists": True}}


def test_client_clip_id_is_unique_per_feed(repo):
    repo.insert(doc("m1", client_clip_id="c1"))
    with pytest.raises(DuplicateKeyError):
        repo.insert(doc("m2", client_clip_id="c1"))
    repo.insert(doc("m3", feed_id="f2", client_clip_id="c1"))  # another feed may reuse it
    assert repo.by_client_clip_id("f1", "c1")["_id"] == "m1"


def test_clips_without_client_id_never_collide(repo):
    repo.insert(doc("m1"))
    repo.insert(doc("m2"))
    assert repo.by_client_clip_id("f1", "anything") is None


def test_list_get_and_recent(repo):
    for i in range(7):
        repo.insert(doc(f"m{i}", minutes=i, house_id="h1" if i % 2 else "h2"))
    items, total = repo.list({"house_id": "h1"}, offset=0, limit=2)
    assert total == 3
    assert [d["_id"] for d in items] == ["m5", "m3"]
    assert repo.get("m4", {"house_id": {"$in": ["h2"]}})["_id"] == "m4"
    assert repo.get("m4", {"house_id": {"$in": ["h1"]}}) is None
    assert [d["_id"] for d in repo.recent_for_feed("f1")] == ["m6", "m5", "m4", "m3", "m2"]
    stored = repo.get("m0", {})
    assert stored["captured_at"] == T0  # tz-aware UTC round trip
