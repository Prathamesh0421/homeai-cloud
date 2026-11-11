"""``media_events`` indexes (contract 02 §4.1; C1 owns the collection and its indexes).

Idempotent: ``create_index`` is a no-op when an identical index already exists, so this runs on
every startup.
"""

from __future__ import annotations

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

MEDIA_EVENTS = "media_events"


def ensure_indexes(media_events: Collection) -> None:
    # The C3 worker claims the oldest queued clip.
    media_events.create_index([("status", ASCENDING), ("uploaded_at", ASCENDING)])
    # Clip Library: newest first per house.
    media_events.create_index([("house_id", ASCENDING), ("captured_at", DESCENDING)])
    # Exactly-once ingest per device clip id (only when the client sent one).
    media_events.create_index(
        [("feed_id", ASCENDING), ("client_clip_id", ASCENDING)],
        unique=True,
        partialFilterExpression={"client_clip_id": {"$exists": True}},
    )
