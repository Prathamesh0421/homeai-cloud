"""In-memory fakes that match the real adapters' behavior.

A fake is only legal when a Tier 3 contract test (tests/contract/) proves it behaves like the
real thing on the points tests rely on. ``FakeDetectionRepo`` deliberately reproduces Mongo's
``_id`` immutability on replace (the bug a naive append-only fake hid in Phase 5).
"""

from __future__ import annotations


class FakeDetectionRepo:
    """Behaves like DetectionRepo on a real collection, including stable ``_id`` on replace."""

    def __init__(self):
        self.docs: dict[str, dict] = {}  # media_id -> detection

    def exists_for_media(self, media_id: str) -> bool:
        return media_id in self.docs

    def get_by_media(self, media_id: str) -> dict | None:
        return self.docs.get(media_id)

    def upsert_by_media(self, detection: dict) -> None:
        existing = self.docs.get(detection["media_id"])
        if existing is not None:
            # Mongo refuses to change _id on a replace; mirror that and write it back.
            detection["_id"] = existing["_id"]
        self.docs[detection["media_id"]] = detection


class FakeMediaEventRepo:
    """Minimal media-event store for pipeline control-flow tests."""

    def __init__(self):
        self.events: dict[str, dict] = {}
        self.analyzed: list[tuple] = []

    def get(self, media_id: str) -> dict | None:
        return self.events.get(media_id)

    def mark_analyzed(self, media_id: str, detection_id: str, handoff_status: str) -> None:
        self.analyzed.append((media_id, detection_id, handoff_status))
        if media_id in self.events:
            self.events[media_id].update(
                status="analyzed", detection_id=detection_id, handoff_status=handoff_status
            )
