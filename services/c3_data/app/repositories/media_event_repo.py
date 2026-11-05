"""``media_events`` processing-field writer (MongoDB; contract §4.1, docs §4.1).

C1 owns the collection and inserts documents; **C3 only updates the processing fields**
(``status``, ``attempts``, ``claimed_at``, ``worker_id``, ``error``, ``detection_id``,
``handoff_status``). The claim is an atomic ``find_one_and_update`` so two workers never take
the same clip; it also reclaims clips stuck in ``processing`` past the visibility timeout.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pymongo import ASCENDING, ReturnDocument
from pymongo.collection import Collection

COLLECTION = "media_events"

MAX_ATTEMPTS = 3
VISIBILITY_TIMEOUT_SECONDS = 120


def _now() -> datetime:
    return datetime.now(UTC)


class MediaEventRepo:
    def __init__(self, collection: Collection):
        self.collection = collection

    def get(self, media_id: str) -> dict | None:
        return self.collection.find_one({"_id": media_id})

    def claim_next(self, worker_id: str, now: datetime | None = None) -> dict | None:
        """Atomically claim the oldest queued (or timed-out processing) clip.

        Sets status=processing, claimed_at=now, worker_id, and increments attempts. Returns the
        claimed document (post-update) or None if the queue is empty.
        """
        now = now or _now()
        stale_before = now - timedelta(seconds=VISIBILITY_TIMEOUT_SECONDS)
        return self.collection.find_one_and_update(
            {
                "$or": [
                    {"status": "queued"},
                    {"status": "processing", "claimed_at": {"$lt": stale_before}},
                ]
            },
            {
                "$set": {"status": "processing", "claimed_at": now, "worker_id": worker_id},
                "$inc": {"attempts": 1},
            },
            sort=[("uploaded_at", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )

    def mark_analyzed(self, media_id: str, detection_id: str, handoff_status: str) -> None:
        self.collection.update_one(
            {"_id": media_id},
            {
                "$set": {
                    "status": "analyzed",
                    "detection_id": detection_id,
                    "handoff_status": handoff_status,
                    "error": None,
                }
            },
        )

    def mark_failure(self, media_id: str, attempts: int, error: str) -> str:
        """Back to queued if attempts remain, else failed. Returns the new status."""
        new_status = "queued" if attempts < MAX_ATTEMPTS else "failed"
        self.collection.update_one(
            {"_id": media_id},
            {"$set": {"status": new_status, "error": error[:500]}},
        )
        return new_status

    def set_handoff_status(self, media_id: str, handoff_status: str) -> None:
        self.collection.update_one({"_id": media_id}, {"$set": {"handoff_status": handoff_status}})

    def requeue(self, media_id: str) -> bool:
        """Reset a failed clip to queued (used by the requeue endpoint in Phase 7)."""
        res = self.collection.update_one(
            {"_id": media_id, "status": "failed"},
            {"$set": {"status": "queued", "attempts": 0, "error": None}},
        )
        return res.modified_count == 1
