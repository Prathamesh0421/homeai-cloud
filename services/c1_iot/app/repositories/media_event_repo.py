"""``media_events`` documents (MongoDB; contract 02 §4.1; owner C1).

C1 inserts every field with ``status=queued``, ``attempts=0``, ``handoff_status="none"``; only C3
updates the processing fields afterwards. ``_id`` is the ``media_id`` (UUID string).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pymongo import DESCENDING
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

__all__ = ["DuplicateKeyError", "MediaEventRepository", "new_media_event"]


def new_media_event(
    *,
    media_id: str,
    tenant_id: str,
    house_id: str,
    room_id: str | None,
    feed_id: str,
    media_kind: str,
    bucket: str,
    key: str,
    size: int,
    content_type: str,
    captured_at: datetime,
    uploaded_at: datetime,
    client_clip_id: str | None,
) -> dict[str, Any]:
    """The exact contract document. ``client_clip_id`` is left out when the client sent none, so
    the unique partial index (``$exists``) only covers clips that have one."""
    doc: dict[str, Any] = {
        "_id": media_id,
        "tenant_id": tenant_id,
        "house_id": house_id,
        "room_id": room_id,
        "feed_id": feed_id,
        "media_kind": media_kind,
        "s3": {"bucket": bucket, "key": key, "size": size, "content_type": content_type},
        "captured_at": captured_at,
        "uploaded_at": uploaded_at,
        "status": "queued",
        "attempts": 0,
        "claimed_at": None,
        "worker_id": None,
        "error": None,
        "detection_id": None,
        "handoff_status": "none",
    }
    if client_clip_id is not None:
        doc["client_clip_id"] = client_clip_id
    return doc


class MediaEventRepository:
    def __init__(self, collection: Collection):
        self.collection = collection

    def insert(self, doc: dict[str, Any]) -> None:
        """Raises ``DuplicateKeyError`` when the feed already has this ``client_clip_id``."""
        self.collection.insert_one(doc)

    def by_client_clip_id(self, feed_id: str, client_clip_id: str) -> dict[str, Any] | None:
        return self.collection.find_one({"feed_id": feed_id, "client_clip_id": client_clip_id})

    def get(self, media_id: str, scope_filter: dict[str, Any]) -> dict[str, Any] | None:
        return self.collection.find_one({"_id": media_id, **scope_filter})

    def list(
        self, query: dict[str, Any], *, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        total = self.collection.count_documents(query)
        cursor = (
            self.collection.find(query)
            .sort([("captured_at", DESCENDING), ("_id", DESCENDING)])
            .skip(offset)
            .limit(limit)
        )
        return list(cursor), total

    def recent_for_feed(self, feed_id: str, limit: int = 5) -> list[dict[str, Any]]:
        cursor = (
            self.collection.find({"feed_id": feed_id})
            .sort([("captured_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit)
        )
        return list(cursor)
