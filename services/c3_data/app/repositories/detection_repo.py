"""``ai_detections`` writer (MongoDB, owner c3_app; contract §4.2).

C3 owns this collection; C2 reads it. The document shape must match contract §4.2 exactly
(``_id``, ``media_id``, ``tenant_id``, ``house_id``, ``room_id``, ``model``, ``labels``,
``top_label``, ``top_confidence``, ``detected_at``). Upsert is keyed by ``media_id`` so a
re-classify (force) replaces the previous detection for a clip, keeping its ``_id``: Mongo
does not allow a replacement to change ``_id``, and C2 is idempotent on ``detection_id``, so a
stable id means a re-classify never raises a second alert for the same clip.
"""

from __future__ import annotations

from pymongo.collection import Collection

COLLECTION = "ai_detections"


class DetectionRepo:
    def __init__(self, collection: Collection):
        self.collection = collection

    def exists_for_media(self, media_id: str) -> bool:
        return self.collection.find_one({"media_id": media_id}, {"_id": 1}) is not None

    def get_by_media(self, media_id: str) -> dict | None:
        return self.collection.find_one({"media_id": media_id})

    def upsert_by_media(self, detection: dict) -> None:
        """Insert or replace the detection for ``detection['media_id']``.

        A replacement keeps the existing ``_id`` (and sets it on ``detection``, so the caller
        records and hands off the id that is actually stored).
        """
        existing = self.collection.find_one({"media_id": detection["media_id"]}, {"_id": 1})
        if existing is not None:
            detection["_id"] = existing["_id"]
        self.collection.replace_one({"media_id": detection["media_id"]}, detection, upsert=True)
