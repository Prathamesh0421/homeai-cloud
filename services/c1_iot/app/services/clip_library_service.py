"""Clip Library (C1 plan §3.3): scoped clip lists, detail and presigned playback URLs.

Feed and room names come from Postgres in one batch per page. ``top_label`` is read from C3's
``ai_detections`` when that collection is reachable; it is optional, so a failure there only
leaves it empty.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeai_common.errors import ApiError
from pymongo.collection import Collection
from sqlalchemy.orm import Session

from app.gateways.s3_media_gateway import MediaStorage, StorageError
from app.repositories.feed_repo import FeedRepository, FeedRow
from app.repositories.media_event_repo import MediaEventRepository
from app.repositories.scope import Scope
from app.schemas.clip import ClipDetailOut, ClipOut, PlaybackUrlOut
from app.schemas.common import to_utc
from app.schemas.feed import RecentClip
from app.services.errors import not_found

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClipFilters:
    house_id: str | None = None
    feed_id: str | None = None
    room_id: str | None = None
    status: str | None = None
    from_: datetime | None = None
    to: datetime | None = None

    def query(self, scope: Scope) -> dict[str, Any]:
        query = scope.mongo_filter()
        if self.house_id:
            if "house_id" in query and self.house_id not in query["house_id"]["$in"]:
                query["house_id"] = {"$in": []}  # an owner asking for someone else's house
            else:
                query["house_id"] = self.house_id
        for field in ("feed_id", "room_id", "status"):
            value = getattr(self, field)
            if value:
                query[field] = value
        window: dict[str, datetime] = {}
        if self.from_:
            window["$gte"] = to_utc(self.from_)
        if self.to:
            window["$lt"] = to_utc(self.to)
        if window:
            query["captured_at"] = window
        return query


def recent_clip(doc: dict[str, Any]) -> RecentClip:
    return RecentClip(
        media_id=doc["_id"],
        media_kind=doc["media_kind"],
        captured_at=doc["captured_at"],
        uploaded_at=doc["uploaded_at"],
        size=doc["s3"]["size"],
        status=doc["status"],
        detection_id=doc.get("detection_id"),
    )


class ClipLibraryService:
    def __init__(
        self,
        session: Session,
        media: MediaEventRepository,
        storage: MediaStorage | None = None,
        *,
        detections: Collection | None = None,
        presign_ttl_s: int = 900,
    ):
        self.session = session
        self.feeds = FeedRepository(session)
        self.media = media
        self.storage = storage
        self.detections = detections
        self.presign_ttl_s = presign_ttl_s

    def _labels(self, docs: list[dict[str, Any]]) -> dict[str, tuple[str, float]]:
        """``{media_id: (top_label, top_confidence)}`` from ai_detections (best effort)."""
        if self.detections is None or not docs:
            return {}
        try:
            cursor = self.detections.find(
                {"media_id": {"$in": [d["_id"] for d in docs]}},
                {"media_id": 1, "top_label": 1, "top_confidence": 1},
            )
            return {d["media_id"]: (d.get("top_label"), d.get("top_confidence")) for d in cursor}
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.warning("ai_detections unavailable", extra={"error": str(exc)[:200]})
            return {}

    @staticmethod
    def _clip(doc: dict[str, Any], row: FeedRow | None, label: tuple[str, float] | None) -> dict:
        return {
            "media_id": doc["_id"],
            "house_id": doc["house_id"],
            "feed_id": doc["feed_id"],
            "feed_name": row.feed.name if row else None,
            "room_id": doc.get("room_id"),
            "room_name": row.room_name if row else None,
            "media_kind": doc["media_kind"],
            "captured_at": doc["captured_at"],
            "uploaded_at": doc["uploaded_at"],
            "size": doc["s3"]["size"],
            "status": doc["status"],
            "detection_id": doc.get("detection_id"),
            "top_label": label[0] if label else None,
        }

    def list_clips(
        self, scope: Scope, filters: ClipFilters, *, offset: int, limit: int
    ) -> tuple[list[ClipOut], int]:
        docs, total = self.media.list(filters.query(scope), offset=offset, limit=limit)
        rows = self.feeds.by_ids([d["feed_id"] for d in docs])
        labels = self._labels(docs)
        items = [
            ClipOut(**self._clip(d, rows.get(d["feed_id"]), labels.get(d["_id"]))) for d in docs
        ]
        return items, total

    def _doc(self, media_id: str, scope: Scope) -> dict[str, Any]:
        doc = self.media.get(media_id, scope.mongo_filter())
        if doc is None:
            raise not_found("clip")
        return doc

    def get_clip(self, media_id: str, scope: Scope) -> ClipDetailOut:
        doc = self._doc(media_id, scope)
        row = self.feeds.by_ids([doc["feed_id"]]).get(doc["feed_id"])
        label = self._labels([doc]).get(media_id)
        return ClipDetailOut(
            **self._clip(doc, row, label),
            tenant_id=doc["tenant_id"],
            content_type=doc["s3"]["content_type"],
            s3_key=doc["s3"]["key"],
            client_clip_id=doc.get("client_clip_id"),
            attempts=doc.get("attempts", 0),
            error=doc.get("error"),
            handoff_status=doc.get("handoff_status"),
            top_confidence=label[1] if label else None,
        )

    def playback_url(self, media_id: str, scope: Scope) -> PlaybackUrlOut:
        doc = self._doc(media_id, scope)
        if self.storage is None:  # pragma: no cover - always configured by create_app
            raise ApiError(503, "storage_unavailable", "clip storage is not configured")
        try:
            url, expires_at = self.storage.presign(doc["s3"]["key"], self.presign_ttl_s)
        except StorageError as exc:
            raise ApiError(503, "storage_unavailable", "could not sign the playback URL") from exc
        return PlaybackUrlOut(url=url, expires_at=expires_at)

    def recent_for_feed(self, feed_id: str) -> list[RecentClip]:
        try:
            return [recent_clip(d) for d in self.media.recent_for_feed(feed_id)]
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.warning("media_events unavailable", extra={"error": str(exc)[:200]})
            return []
