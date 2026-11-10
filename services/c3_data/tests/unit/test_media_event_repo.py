"""C3-06: media_events claim query shape and retry/fail threshold."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.repositories.media_event_repo import (
    MAX_ATTEMPTS,
    VISIBILITY_TIMEOUT_SECONDS,
    MediaEventRepo,
)


class _FakeCollection:
    def __init__(self):
        self.calls: list[dict] = []
        self.updates: list[tuple] = []

    def find_one_and_update(self, query, update, **kwargs):
        self.calls.append({"query": query, "update": update, "kwargs": kwargs})
        return {"_id": "m1", "attempts": 1}

    def update_one(self, flt, update):
        self.updates.append((flt, update))

        class _R:
            modified_count = 1

        return _R()


def test_claim_query_targets_queued_or_stale_processing():
    col = _FakeCollection()
    repo = MediaEventRepo(col)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    repo.claim_next("w1", now=now)

    call = col.calls[0]
    conds = call["query"]["$or"]
    assert {"status": "queued"} in conds
    stale = next(c for c in conds if c["status"] == "processing")
    assert stale["claimed_at"]["$lt"] == now - timedelta(seconds=VISIBILITY_TIMEOUT_SECONDS)
    assert call["update"]["$set"]["worker_id"] == "w1"
    assert call["update"]["$set"]["status"] == "processing"
    assert call["update"]["$inc"] == {"attempts": 1}
    assert call["kwargs"]["sort"] == [("uploaded_at", 1)]


def test_mark_failure_requeues_until_max_then_fails():
    col = _FakeCollection()
    repo = MediaEventRepo(col)
    assert repo.mark_failure("m1", attempts=1, error="boom") == "queued"
    assert repo.mark_failure("m1", attempts=MAX_ATTEMPTS, error="boom") == "failed"
    # error is truncated to 500 chars
    repo.mark_failure("m1", attempts=1, error="x" * 1000)
    assert len(col.updates[-1][1]["$set"]["error"]) == 500


def test_requeue_resets_failed_clip():
    col = _FakeCollection()
    repo = MediaEventRepo(col)
    assert repo.requeue("m1") is True
    flt, update = col.updates[-1]
    assert flt == {"_id": "m1", "status": "failed"}
    assert update["$set"] == {"status": "queued", "attempts": 0, "error": None}


def test_mark_analyzed_clears_claim_fields():
    # C3-12 §5: an analyzed clip must not keep a stale claimed_at/worker_id, which the
    # integrity check would otherwise read as a half-finished claim.
    col = _FakeCollection()
    repo = MediaEventRepo(col)
    repo.mark_analyzed("m1", detection_id="d1", handoff_status="done")
    flt, update = col.updates[-1]
    assert flt == {"_id": "m1"}
    assert update["$set"]["status"] == "analyzed"
    assert update["$set"]["detection_id"] == "d1"
    assert update["$unset"] == {"claimed_at": "", "worker_id": ""}
