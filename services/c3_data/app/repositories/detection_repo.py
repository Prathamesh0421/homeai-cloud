"""``ai_detections`` writer (MongoDB, owner c3_app; contract §4.2).

C3 owns this collection; C2 reads it. The document shape must match contract §4.2 exactly
(``_id``, ``media_id``, ``tenant_id``, ``house_id``, ``room_id``, ``model``, ``labels``,
``top_label``, ``top_confidence``, ``detected_at``). Upsert is keyed by ``media_id`` so a
re-classify (force) replaces the previous detection for a clip.
"""

from __future__ import annotations

from pymongo.collection import Collection

COLLECTION = "ai_detections"


class DetectionRepo:
    def __init__(self, collection: Collection):
        self.collection = collection

    def exists_for_media(self, media_id: str) -> bool:
        return self.collection.find_one({"media_id": media_id}, {"_id": 1}) is not None

    def upsert_by_media(self, detection: dict) -> None:
        """Insert or replace the detection for ``detection['media_id']``."""
        self.collection.replace_one({"media_id": detection["media_id"]}, detection, upsert=True)
