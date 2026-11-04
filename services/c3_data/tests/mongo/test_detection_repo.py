"""DetectionRepo against real MongoDB (``MONGO_URL_C3``; CI provides it, locally it skips).

The fakes in the unit tests cannot show what Mongo refuses, e.g. a replacement that changes
``_id``.
"""

from __future__ import annotations

import os
import uuid

import pytest
from app.repositories.detection_repo import DetectionRepo
from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL_C3")


def _unavailable(reason: str) -> None:
    if os.environ.get("CI") == "true":
        pytest.fail(f"MongoDB required on CI: {reason}", pytrace=False)
    pytest.skip(reason)


@pytest.fixture
def repo():
    if not MONGO_URL:
        _unavailable("MONGO_URL_C3 not set")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
    except Exception as exc:
        _unavailable(f"MongoDB unreachable: {type(exc).__name__}")
    collection = client.get_default_database()[f"ai_detections_test_{uuid.uuid4().hex[:8]}"]
    yield DetectionRepo(collection)
    collection.drop()
    client.close()


def _detection(media_id: str, top_label: str) -> dict:
    return {"_id": str(uuid.uuid4()), "media_id": media_id, "top_label": top_label}


def test_reclassify_replaces_the_detection_and_keeps_its_id(repo):
    first = _detection("media-1", "speech")
    repo.upsert_by_media(first)

    again = _detection("media-1", "glass_break")  # a fresh _id, as the pipeline builds it
    repo.upsert_by_media(again)

    stored = list(repo.collection.find({"media_id": "media-1"}))
    assert len(stored) == 1
    assert stored[0]["_id"] == first["_id"]  # C2 sees the same detection_id: no second alert
    assert stored[0]["top_label"] == "glass_break"
    assert again["_id"] == first["_id"]  # the caller hands off the id that is stored


def test_get_by_media(repo):
    assert repo.get_by_media("media-1") is None
    doc = _detection("media-1", "speech")
    repo.upsert_by_media(doc)
    assert repo.get_by_media("media-1")["_id"] == doc["_id"]
    assert repo.exists_for_media("media-1")
