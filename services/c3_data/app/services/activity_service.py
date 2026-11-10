"""Activity rollup hook + baseline job (C3-11, Rev3 §6.2)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from pymongo.database import Database

from app.repositories.activity_repo import COLLECTION, ActivityRepo

logger = logging.getLogger("c3.activity")


def build_rollup(mongo: Database) -> Callable[[dict], None]:
    """Return the pipeline's ``on_rollup`` hook. Idempotent by detection_id, so it is safe to
    call from both classify and finish_existing and on any replay."""
    repo = ActivityRepo(mongo[COLLECTION])

    def _rollup(detection: dict) -> None:
        counted = repo.rollup(detection)
        if not counted:
            logger.info(
                "activity rollup skipped (already counted)",
                extra={"detection_id": detection["_id"]},
            )

    return _rollup


def run_baseline_job(mongo: Database, as_of: datetime | None = None) -> int:
    """Nightly job: recompute baseline + anomaly for every house/room with a bucket today.

    Idempotent and safe on one instance. Returns the number of (house, room) pairs updated.
    """
    as_of = (as_of or datetime.now(UTC)).astimezone(UTC)
    repo = ActivityRepo(mongo[COLLECTION])
    today = f"{as_of:%Y-%m-%d}"
    pairs = {
        (doc["house_id"], doc["room_id"])
        for doc in mongo[COLLECTION].find({"date": today}, {"house_id": 1, "room_id": 1})
    }
    updated = 0
    for house_id, room_id in pairs:
        if repo.compute_baseline(house_id, room_id, as_of) is not None:
            updated += 1
    logger.info("baseline job done", extra={"pairs": len(pairs), "updated": updated})
    return updated
