"""C3 ``ai_detections`` reader (MongoDB, read-only user ``c2_reader``; contract §4.2)."""

from __future__ import annotations

from pydantic import ValidationError
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.gateways.types import DependencyUnavailableError, Detection, InvalidDetectionError

SOURCE = "c3"
COLLECTION = "ai_detections"


class MongoDetectionGateway:
    """Implements ``DetectionReader``."""

    def __init__(self, collection: Collection):
        self.collection = collection

    def get(self, detection_id: str) -> Detection | None:
        try:
            doc = self.collection.find_one({"_id": detection_id})
        except PyMongoError as exc:
            raise DependencyUnavailableError(SOURCE, type(exc).__name__) from exc
        if doc is None:
            return None
        try:
            return Detection.model_validate(doc)
        except ValidationError as exc:
            fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
            raise InvalidDetectionError(f"detection {detection_id}: bad fields {fields}") from exc
