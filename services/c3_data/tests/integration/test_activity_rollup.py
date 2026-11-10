"""C3-11 (Tier 2): idempotent activity rollup + baseline on real Mongo (Rev3 §6.2).

The exactly-once guarantee is the whole point: retries, the 120 s reclaim, finish_existing, and
force re-classify all replay the tail of the pipeline. These assert the real count, not "no
error". All UTC.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.repositories.activity_repo import (
    MIN_BASELINE_DAYS,
    ActivityRepo,
    band,
    bucket_id,
)
from app.services.activity_service import build_rollup, run_baseline_job

pytestmark = pytest.mark.integration

HOUSE = "22222222-0000-0000-0000-0000000000a1"
ROOM = "33333333-0000-0000-0000-0000000000a1"
TENANT = "11111111-0000-0000-0000-0000000000a1"


class _OneColDb:
    """A Database shim that always returns the same activity_patterns collection.

    The shared mongo_db fixture hands out a *fresh* uniquely-named collection on every
    __getitem__, which is right for isolating repos but wrong for build_rollup (it looks up
    'activity_patterns' internally) paired with a separate read. Pin one collection so writes
    and reads land together.
    """

    def __init__(self, col):
        self._col = col

    def __getitem__(self, _name):
        return self._col


@pytest.fixture
def repo(mongo_db):
    col = mongo_db["activity_patterns"]
    return ActivityRepo(col), col


@pytest.fixture
def one_col_db(mongo_db):
    """A stable single-collection DB for build_rollup / run_baseline_job tests."""
    return _OneColDb(mongo_db["activity_patterns"])


def _detection(house=HOUSE, room=ROOM, when=None, did=None, tenant=TENANT):
    return {
        "_id": did or str(uuid.uuid4()),
        "media_id": str(uuid.uuid4()),
        "tenant_id": tenant,
        "house_id": house,
        "room_id": room,
        "top_label": "glass_break",
        "detected_at": when or datetime(2026, 6, 1, 14, 30, tzinfo=UTC),
    }


def _count_at(repo, when, house=HOUSE, room=ROOM):
    doc = repo.get(house, room, f"{when.astimezone(UTC):%Y-%m-%d}")
    return doc["hours"][when.astimezone(UTC).hour] if doc else 0


# -- exactly-once -------------------------------------------------------------------------
def test_single_detection_rolls_once(repo):
    r, _ = repo
    when = datetime(2026, 6, 1, 14, 0, tzinfo=UTC)
    assert r.rollup(_detection(when=when)) is True
    assert _count_at(r, when) == 1


def test_replay_same_detection_id_is_noop(repo):
    r, _ = repo
    when = datetime(2026, 6, 1, 14, 0, tzinfo=UTC)
    det = _detection(when=when)
    assert r.rollup(det) is True
    assert r.rollup(det) is False  # replay: not counted
    assert r.rollup(det) is False
    assert _count_at(r, when) == 1  # still 1


def test_force_reclassify_rolls_once(repo):
    # A re-classify keeps the same detection_id (Rev1 §8); rolling it again must not double-count.
    r, _ = repo
    when = datetime(2026, 6, 1, 14, 0, tzinfo=UTC)
    did = str(uuid.uuid4())
    r.rollup(_detection(when=when, did=did))
    r.rollup(_detection(when=when, did=did))  # re-classify, same id
    assert _count_at(r, when) == 1


def test_two_distinct_detections_same_bucket_count_two(repo):
    r, _ = repo
    when = datetime(2026, 6, 1, 14, 0, tzinfo=UTC)
    r.rollup(_detection(when=when))
    r.rollup(_detection(when=when))  # different id
    assert _count_at(r, when) == 2


# -- crash-and-resume via the pipeline hook ------------------------------------------------
def test_finish_existing_resume_rolls_exactly_once_crash_before_rollup(one_col_db):
    """First attempt crashed BEFORE the rollup; finish_existing applies it exactly once."""
    rollup = build_rollup(one_col_db)
    r = ActivityRepo(one_col_db["activity_patterns"])
    when = datetime(2026, 6, 2, 9, 0, tzinfo=UTC)
    det = _detection(when=when)
    # Simulate: detection stored, but rollup never ran (crash before step 7). finish_existing
    # then calls the rollup hook once.
    rollup(det)
    assert _count_at(r, when, room=ROOM) == 1


def test_resume_after_rollup_does_not_double_count(one_col_db):
    """First attempt DID roll up, then crashed; the resume calls the hook again -> still 1."""
    rollup = build_rollup(one_col_db)
    r = ActivityRepo(one_col_db["activity_patterns"])
    when = datetime(2026, 6, 2, 10, 0, tzinfo=UTC)
    det = _detection(when=when)
    rollup(det)  # first attempt rolled up
    rollup(det)  # resume replays the hook
    assert _count_at(r, when) == 1


def test_two_workers_reclaim_counts_one(one_col_db):
    """Two workers process the same reclaimed clip (same detection_id) -> count 1, not 2."""
    r = ActivityRepo(one_col_db["activity_patterns"])
    w1, w2 = build_rollup(one_col_db), build_rollup(one_col_db)
    when = datetime(2026, 6, 2, 11, 0, tzinfo=UTC)
    det = _detection(when=when)
    w1(det)
    w2(det)  # the reclaiming worker replays the same detection_id
    assert _count_at(r, when) == 1


# -- UTC bucketing -------------------------------------------------------------------------
def test_bucketing_is_utc(repo):
    r, _ = repo
    # 23:30 UTC on 2026-06-01 must land in hour 23 of 2026-06-01 (not a local-time shift).
    when = datetime(2026, 6, 1, 23, 30, tzinfo=UTC)
    r.rollup(_detection(when=when))
    doc = r.get(HOUSE, ROOM, "2026-06-01")
    assert doc is not None
    assert doc["hours"][23] == 1
    assert doc["_id"] == bucket_id(HOUSE, ROOM, when)


# -- baseline + anomaly + cold start -------------------------------------------------------
def _seed_days(col, n_days, as_of, per_hour=2, hour=14, house=HOUSE, room=ROOM):
    for d in range(1, n_days + 1):
        day = as_of - timedelta(days=d)
        hours = [0] * 24
        hours[hour] = per_hour
        col.replace_one(
            {"_id": f"{house}:{room}:{day:%Y-%m-%d}"},
            {
                "_id": f"{house}:{room}:{day:%Y-%m-%d}",
                "tenant_id": TENANT,
                "house_id": house,
                "room_id": room,
                "date": f"{day:%Y-%m-%d}",
                "hours": hours,
                "counted": [],
            },
            upsert=True,
        )


def test_baseline_mean_and_std_over_28_days(repo):
    r, col = repo
    as_of = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    _seed_days(col, 28, as_of, per_hour=2, hour=14)
    # Today's bucket (normal activity at hour 14).
    r.rollup(_detection(when=datetime(2026, 7, 1, 14, 0, tzinfo=UTC)))
    r.rollup(_detection(when=datetime(2026, 7, 1, 14, 0, tzinfo=UTC)))

    doc = r.compute_baseline(HOUSE, ROOM, as_of)
    assert doc is not None
    assert doc["baseline_mean"][14] == pytest.approx(2.0)  # constant 2/day -> mean 2
    assert doc["baseline_std"][14] == pytest.approx(0.0)  # no variance
    # count==mean -> anomaly 0 -> normal band.
    assert doc["anomaly_score"] == pytest.approx(0.0, abs=1e-6)
    assert band(doc["anomaly_score"]) == "normal"


def test_anomaly_flags_spike(repo):
    r, col = repo
    as_of = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    _seed_days(col, 28, as_of, per_hour=1, hour=14)
    # Today: a big spike at hour 14.
    for _ in range(20):
        r.rollup(_detection(when=datetime(2026, 7, 1, 14, 0, tzinfo=UTC)))
    doc = r.compute_baseline(HOUSE, ROOM, as_of)
    assert doc["anomaly_score"] > 0


def test_cold_start_suppresses_anomaly(repo):
    r, col = repo
    as_of = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    # Only a few days of history (< MIN_BASELINE_DAYS): band must be suppressed.
    _seed_days(col, 3, as_of, per_hour=1, hour=14)
    for _ in range(20):  # a spike that WOULD be anomalous with a mature baseline
        r.rollup(_detection(when=datetime(2026, 7, 1, 14, 0, tzinfo=UTC)))
    assert MIN_BASELINE_DAYS > 3
    doc = r.compute_baseline(HOUSE, ROOM, as_of)
    assert doc["anomaly_score"] is None
    assert band(doc["anomaly_score"]) == "insufficient_data"


def test_run_baseline_job_scores_todays_pairs(one_col_db):
    col = one_col_db["activity_patterns"]
    r = ActivityRepo(col)
    as_of = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    _seed_days(col, MIN_BASELINE_DAYS + 1, as_of, per_hour=2, hour=14)
    r.rollup(_detection(when=datetime(2026, 7, 1, 14, 0, tzinfo=UTC)))
    updated = run_baseline_job(one_col_db, as_of=as_of)
    assert updated == 1
    doc = r.get(HOUSE, ROOM, "2026-07-01")
    assert doc["baseline_mean"][14] == pytest.approx(2.0)
