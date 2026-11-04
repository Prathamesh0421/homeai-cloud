"""C3-02: Mongo index specs (ai_detections, activity_patterns, worker_heartbeats TTL)."""

from __future__ import annotations

from app.db.mongo_indexes import HEARTBEAT_TTL_SECONDS, ensure_indexes


class _FakeCollection:
    def __init__(self):
        self.indexes: list[dict] = []

    def create_index(self, keys, **kwargs):
        self.indexes.append({"keys": keys, **kwargs})
        return kwargs.get("name", "idx")


class _FakeDb:
    def __init__(self):
        self._cols: dict[str, _FakeCollection] = {}

    def __getitem__(self, name):
        return self._cols.setdefault(name, _FakeCollection())


def test_ensure_indexes_creates_expected_indexes():
    db = _FakeDb()
    ensure_indexes(db)

    det = {i["name"]: i for i in db["ai_detections"].indexes}
    assert det["ux_media_id"]["keys"] == [("media_id", 1)]
    assert det["ux_media_id"]["unique"] is True
    assert det["ix_house_detected"]["keys"] == [("house_id", 1), ("detected_at", -1)]
    assert det["ix_house_label_detected"]["keys"] == [
        ("house_id", 1),
        ("top_label", 1),
        ("detected_at", -1),
    ]
    assert det["ix_tenant_detected"]["keys"] == [("tenant_id", 1), ("detected_at", -1)]

    pat = {i["name"]: i for i in db["activity_patterns"].indexes}
    assert pat["ix_house_room_date"]["keys"] == [
        ("house_id", 1),
        ("room_id", 1),
        ("date", -1),
    ]

    hb = {i["name"]: i for i in db["worker_heartbeats"].indexes}
    assert hb["ttl_last_heartbeat"]["expireAfterSeconds"] == HEARTBEAT_TTL_SECONDS == 600


def test_ensure_indexes_is_idempotent_shape():
    # Calling twice must not raise; create_index itself is idempotent in real pymongo.
    db = _FakeDb()
    ensure_indexes(db)
    ensure_indexes(db)
    assert len(db["ai_detections"].indexes) == 8  # 4 specs x 2 calls
