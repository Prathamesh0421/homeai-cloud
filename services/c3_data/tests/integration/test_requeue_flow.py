"""C3-12 (Tier 2): requeue a failed clip on real Mongo — idempotent, and reclaimable.

The requeue endpoint resets a failed clip to queued; the DoD requires that a worker can then
pick it up and that a second requeue is a no-op. Asserted here against the atomic claim_next.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from app.repositories.media_event_repo import MediaEventRepo

pytestmark = pytest.mark.integration

TENANT = "11111111-0000-0000-0000-00000000c1e3"
HOUSE = "22222222-0000-0000-0000-00000000c1e3"


@pytest.fixture
def repo(mongo_db):
    return MediaEventRepo(mongo_db["media_events"])


def _failed_clip(repo) -> str:
    media_id = str(uuid.uuid4())
    repo.collection.insert_one(
        {
            "_id": media_id,
            "tenant_id": TENANT,
            "house_id": HOUSE,
            "room_id": "r1",
            "status": "failed",
            "attempts": 3,
            "error": "boom",
            "uploaded_at": datetime.now(UTC),
        }
    )
    return media_id


def test_requeue_then_worker_claims_it(repo):
    media_id = _failed_clip(repo)

    assert repo.requeue(media_id) is True
    doc = repo.get(media_id)
    assert doc["status"] == "queued"
    assert doc["attempts"] == 0
    assert doc["error"] is None

    # A worker now claims the requeued clip (atomic claim_next).
    claimed = repo.claim_next("worker-x")
    assert claimed is not None
    assert claimed["_id"] == media_id
    assert claimed["status"] == "processing"
    assert claimed["attempts"] == 1  # claim increments from the reset 0


def test_second_requeue_is_a_noop(repo):
    media_id = _failed_clip(repo)

    assert repo.requeue(media_id) is True  # failed -> queued
    # The clip is no longer failed, so a second requeue changes nothing.
    assert repo.requeue(media_id) is False
    doc = repo.get(media_id)
    assert doc["status"] == "queued"
    assert doc["attempts"] == 0
