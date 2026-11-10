"""In-memory stand-ins for S3, ``media_events`` and ``ai_detections`` in API tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.gateways.s3_media_gateway import StorageError
from app.repositories.media_event_repo import DuplicateKeyError


class FakeStorage:
    bucket = "homeai-c1-test"

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.fail_put = False
        self.fail_presign = False

    def put(self, key: str, body: bytes, content_type: str) -> None:
        if self.fail_put:
            raise StorageError("s3 down")
        self.objects[key] = (body, content_type)

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def presign(self, key: str, ttl_seconds: int) -> tuple[str, datetime]:
        if self.fail_presign:
            raise StorageError("cannot sign")
        expires = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=ttl_seconds)
        return f"https://s3.test/{self.bucket}/{key}?X-Amz-Expires={ttl_seconds}", expires


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for field, cond in query.items():
        value = doc.get(field)
        if isinstance(cond, dict):
            if "$in" in cond and value not in cond["$in"]:
                return False
            if "$gte" in cond and not (value is not None and value >= cond["$gte"]):
                return False
            if "$lt" in cond and not (value is not None and value < cond["$lt"]):
                return False
        elif value != cond:
            return False
    return True


class FakeMediaRepo:
    """Behaves like ``MediaEventRepository`` (incl. the unique client_clip_id index)."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.fail_insert = False

    def insert(self, doc: dict[str, Any]) -> None:
        if self.fail_insert:
            raise RuntimeError("mongo down")
        if "client_clip_id" in doc and self.by_client_clip_id(
            doc["feed_id"], doc["client_clip_id"]
        ):
            raise DuplicateKeyError("duplicate client_clip_id")
        self.docs[doc["_id"]] = dict(doc)

    def by_client_clip_id(self, feed_id: str, client_clip_id: str) -> dict[str, Any] | None:
        for doc in self.docs.values():
            if doc["feed_id"] == feed_id and doc.get("client_clip_id") == client_clip_id:
                return doc
        return None

    def get(self, media_id: str, scope_filter: dict[str, Any]) -> dict[str, Any] | None:
        doc = self.docs.get(media_id)
        return doc if doc and _matches(doc, scope_filter) else None

    def _sorted(self, docs):
        return sorted(docs, key=lambda d: (d["captured_at"], d["_id"]), reverse=True)

    def list(self, query: dict[str, Any], *, offset: int, limit: int):
        found = self._sorted(d for d in self.docs.values() if _matches(d, query))
        return found[offset : offset + limit], len(found)

    def recent_for_feed(self, feed_id: str, limit: int = 5):
        return self._sorted(d for d in self.docs.values() if d["feed_id"] == feed_id)[:limit]


class FakeDetections:
    """Just enough of a pymongo Collection for ``find({"media_id": {"$in": [...]}})``."""

    def __init__(self, docs: list[dict[str, Any]]):
        self.docs = docs

    def find(self, query: dict[str, Any], projection: dict[str, Any] | None = None):
        wanted = set(query["media_id"]["$in"])
        return [d for d in self.docs if d["media_id"] in wanted]
