"""Create the MongoDB indexes C3 owns (docs/components/C3_DATABASE_AND_AI.md §2.2).

Idempotent: ``create_index`` is a no-op when an identical index already exists, so this is
safe to call on every startup / worker start. C3 owns ``ai_detections``,
``activity_patterns`` and ``worker_heartbeats``; it does not create indexes on
``media_events`` (C1 owns that collection and its indexes).
"""

from __future__ import annotations

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

# TTL for worker heartbeats: a heartbeat older than this is removed, so dead workers
# drop off the deployment panel. 10 minutes per §2.2.
HEARTBEAT_TTL_SECONDS = 600


def ensure_indexes(db: Database) -> None:
    """Create all C3-owned indexes. Safe to call repeatedly."""
    detections = db["ai_detections"]
    detections.create_index([("media_id", ASCENDING)], name="ux_media_id", unique=True)
    detections.create_index(
        [("house_id", ASCENDING), ("detected_at", DESCENDING)], name="ix_house_detected"
    )
    detections.create_index(
        [("house_id", ASCENDING), ("top_label", ASCENDING), ("detected_at", DESCENDING)],
        name="ix_house_label_detected",
    )
    detections.create_index(
        [("tenant_id", ASCENDING), ("detected_at", DESCENDING)], name="ix_tenant_detected"
    )

    patterns = db["activity_patterns"]
    patterns.create_index(
        [("house_id", ASCENDING), ("room_id", ASCENDING), ("date", DESCENDING)],
        name="ix_house_room_date",
    )

    heartbeats = db["worker_heartbeats"]
    heartbeats.create_index(
        [("last_heartbeat", ASCENDING)],
        name="ttl_last_heartbeat",
        expireAfterSeconds=HEARTBEAT_TTL_SECONDS,
    )
