"""Clip ingest (C1 plan §4.1) — the decision table, checked in this order:

| # | Check | Fail result |
|---|---|---|
| 1 | caller allowed (route dependency) | 401/403 |
| 2 | feed exists, not archived, in caller's tenant (service tokens: any tenant) | 404 ``not_found`` |
| 3 | ``is_enabled`` and ``room_id`` set | 409 ``feed_not_enabled`` |
| 4 | ``media_kind`` equals the feed's kind (and the file's content type agrees) | 422 ``media_kind_mismatch`` |
| 5 | content type allowed, size <= limit, ``captured_at`` <= now + 5 min | 422 / 413 |
| 6 | ``client_clip_id`` already stored for this feed | 200 existing record, ``duplicate: true`` |
| 7 | ``put_object`` | 503 ``storage_unavailable``, failures += 1 |
| 8 | insert ``media_events`` (``queued``) | delete the S3 object, 503, failures += 1 |
| 9 | ``touch_last_clip``: online, active, failures reset | — |

Three failures in a row put the feed in ``error``. Step 4's content-type rule is a D3 reading of
the plan: an mp4 sent to an audio feed is a kind mismatch, not a valid upload.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from homeai_common.auth import Principal
from homeai_common.errors import ApiError
from sqlalchemy.orm import Session

from app.gateways.s3_media_gateway import CONTENT_TYPES, MediaStorage, StorageError, build_key
from app.repositories.feed_repo import FeedRepository
from app.repositories.media_event_repo import (
    DuplicateKeyError,
    MediaEventRepository,
    new_media_event,
)
from app.repositories.scope import Scope
from app.schemas.common import to_utc
from app.services.errors import conflict, invalid, not_found

logger = logging.getLogger(__name__)

FUTURE_TOLERANCE = timedelta(minutes=5)
ERROR_AFTER_FAILURES = 3


@dataclass(frozen=True)
class ClipUpload:
    feed_id: str
    media_kind: str
    captured_at: datetime
    client_clip_id: str | None
    content_type: str
    data: bytes
    too_large: bool = False  # the router stopped reading past the limit


@dataclass(frozen=True)
class IngestResult:
    media_id: str
    status: str
    s3_key: str
    duplicate: bool


def utc_now() -> datetime:
    return datetime.now(UTC)


def _base_type(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def _result(doc: dict[str, Any], *, duplicate: bool) -> IngestResult:
    return IngestResult(
        media_id=doc["_id"], status=doc["status"], s3_key=doc["s3"]["key"], duplicate=duplicate
    )


class IngestService:
    def __init__(
        self,
        session: Session,
        media: MediaEventRepository,
        storage: MediaStorage,
        *,
        max_bytes: int,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.session = session
        self.feeds = FeedRepository(session)
        self.media = media
        self.storage = storage
        self.max_bytes = max_bytes
        self.clock = clock

    def _fail(self, feed_id: str, message: str) -> ApiError:
        """Count a storage failure on the feed (committed now) and build the 503."""
        self.feeds.record_failure(feed_id, self.clock(), error_after=ERROR_AFTER_FAILURES)
        self.session.commit()
        return ApiError(503, "storage_unavailable", message)

    def ingest(self, principal: Principal, upload: ClipUpload) -> IngestResult:
        now = self.clock()
        # 2. feed visible to the caller (service tokens: any tenant) and not archived
        feed = self.feeds.get(upload.feed_id, Scope.for_principal(principal))
        if feed is None or feed.archived_at is not None:
            raise not_found("feed")
        # 3. enabled and placed in a room
        if not feed.is_enabled or feed.room_id is None:
            raise conflict("feed_not_enabled", "the feed is disabled or has no room")
        # 4. kind of the request and of the file match the feed
        content_type = _base_type(upload.content_type)
        file_kind = CONTENT_TYPES.get(content_type, (None, None))[1]
        if upload.media_kind != feed.media_kind or (file_kind and file_kind != feed.media_kind):
            raise ApiError(
                422,
                "media_kind_mismatch",
                f"this feed records {feed.media_kind}; the upload is "
                f"{file_kind or upload.media_kind}",
            )
        # 5. content type, size, capture time
        if content_type not in CONTENT_TYPES:
            raise invalid("file", f"content type must be one of {sorted(CONTENT_TYPES)}")
        if upload.too_large or len(upload.data) > self.max_bytes:
            raise ApiError(
                413, "payload_too_large", f"clips are limited to {self.max_bytes // 2**20} MB"
            )
        captured_at = to_utc(upload.captured_at)
        if captured_at > now + FUTURE_TOLERANCE:
            raise invalid("captured_at", "must not be more than 5 minutes in the future")
        # 6. exactly once per device clip id
        if upload.client_clip_id:
            existing = self.media.by_client_clip_id(feed.feed_id, upload.client_clip_id)
            if existing is not None:
                return _result(existing, duplicate=True)
        # 7. object first, so a stored record always has its object
        media_id = str(uuid.uuid4())
        ext = CONTENT_TYPES[content_type][0]
        key = build_key(feed.tenant_id, feed.house_id, feed.feed_id, media_id, ext, now)
        try:
            self.storage.put(key, upload.data, content_type)
        except StorageError as exc:
            logger.warning(
                "clip upload to S3 failed", extra={"feed_id": feed.feed_id, "error": str(exc)[:200]}
            )
            raise self._fail(feed.feed_id, "clip storage is unavailable; try again") from exc
        # 8. record; on failure remove the object so nothing is left orphaned
        doc = new_media_event(
            media_id=media_id,
            tenant_id=feed.tenant_id,
            house_id=feed.house_id,
            room_id=feed.room_id,
            feed_id=feed.feed_id,
            media_kind=feed.media_kind,
            bucket=self.storage.bucket,
            key=key,
            size=len(upload.data),
            content_type=content_type,
            captured_at=captured_at,
            uploaded_at=now,
            client_clip_id=upload.client_clip_id,
        )
        try:
            self.media.insert(doc)
        except DuplicateKeyError as exc:
            # Lost a race with the same client_clip_id: the other upload wins.
            self._compensate(key)
            existing = self.media.by_client_clip_id(feed.feed_id, upload.client_clip_id or "")
            if existing is None:  # pragma: no cover - defensive
                raise self._fail(feed.feed_id, "clip record could not be stored") from exc
            return _result(existing, duplicate=True)
        except Exception as exc:
            logger.warning(
                "media_events insert failed",
                extra={"feed_id": feed.feed_id, "error": str(exc)[:200]},
            )
            self._compensate(key)
            raise self._fail(feed.feed_id, "clip record could not be stored; try again") from exc
        # 9. the feed is alive
        self.feeds.touch_last_clip(feed.feed_id, captured_at, now)
        self.session.commit()
        return _result(doc, duplicate=False)

    def _compensate(self, key: str) -> None:
        try:
            self.storage.delete(key)
        except StorageError:  # pragma: no cover - logged; the integrity check reports orphans
            logger.error("orphaned clip object left in S3", extra={"s3_key": key})
