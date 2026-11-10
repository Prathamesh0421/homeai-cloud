"""C3-12 (Tier 2): integrity checks over real Mongo (Rev4 §5).

Each test plants a specific fault and asserts the finding and its severity. The plant helpers
here are the same shapes the pipeline and rollup write, so the checks cannot drift from the
faults they look for. All UTC.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.repositories.media_event_repo import VISIBILITY_TIMEOUT_SECONDS
from app.services import integrity_service

pytestmark = pytest.mark.integration

TENANT = "11111111-0000-0000-0000-0000000000c1"
HOUSE = "22222222-0000-0000-0000-0000000000c1"
ROOM = "33333333-0000-0000-0000-0000000000c1"


class _MultiColDb:
    """A stable Database shim: one persistent collection per name.

    The shared mongo_db fixture hands out a fresh randomized collection on every __getitem__,
    which is right for single-repo isolation but wrong for run_checks (it reads several named
    collections and must see what we plant). Pin one collection per name.
    """

    def __init__(self, mongo_db):
        self._cols = {
            name: mongo_db[name]
            for name in ("media_events", "ai_detections", "activity_patterns", "worker_heartbeats")
        }

    def __getitem__(self, name):
        return self._cols[name]


@pytest.fixture
def mdb(mongo_db):
    return _MultiColDb(mongo_db)


def _clip(mdb, *, status="queued", tenant=TENANT, house=HOUSE, **extra):
    media_id = str(uuid.uuid4())
    doc = {
        "_id": media_id,
        "tenant_id": tenant,
        "house_id": house,
        "room_id": ROOM,
        "status": status,
        "attempts": 1,
        "uploaded_at": datetime.now(UTC),
    }
    doc.update(extra)
    mdb["media_events"].insert_one(doc)
    return media_id


def _detection(mdb, *, media_id, tenant=TENANT, house=HOUSE, did=None):
    did = did or str(uuid.uuid4())
    mdb["ai_detections"].insert_one(
        {
            "_id": did,
            "media_id": media_id,
            "tenant_id": tenant,
            "house_id": house,
            "room_id": ROOM,
            "top_label": "glass_break",
            "top_confidence": 0.9,
            "detected_at": datetime.now(UTC),
        }
    )
    return did


def _bucket(mdb, *, tenant=TENANT, house=HOUSE, counted, hours=None, date="2026-06-01"):
    hours = hours or [0] * 24
    mdb["activity_patterns"].insert_one(
        {
            "_id": f"{house}:{ROOM}:{date}",
            "tenant_id": tenant,
            "house_id": house,
            "room_id": ROOM,
            "date": date,
            "hours": hours,
            "counted": counted,
        }
    )


def _kinds(findings):
    return {f["kind"] for f in findings}


def _by_entity(findings, entity_id):
    return [f for f in findings if f["entity_id"] == entity_id]


def test_clean_store_has_no_findings(mdb):
    media_id = _clip(mdb, status="analyzed", detection_id="d", handoff_status="done")
    _detection(mdb, media_id=media_id, did="d")
    _bucket(mdb, counted=[], hours=[0] * 24)
    findings = integrity_service.run_checks(mdb, TENANT)
    assert findings == []


def test_orphan_detection_is_medium(mdb):
    did = _detection(mdb, media_id=str(uuid.uuid4()))  # no matching clip
    findings = _by_entity(integrity_service.run_checks(mdb, TENANT), did)
    assert len(findings) == 1
    assert findings[0]["kind"] == "orphan_detection"
    assert findings[0]["severity"] == integrity_service.MEDIUM


def test_analyzed_with_no_detection_is_high(mdb):
    media_id = _clip(mdb, status="analyzed")  # no detection_id set
    findings = _by_entity(integrity_service.run_checks(mdb, TENANT), media_id)
    kinds = {f["kind"]: f for f in findings}
    assert "analyzed_no_detection" in kinds
    assert kinds["analyzed_no_detection"]["severity"] == integrity_service.HIGH


def test_stuck_processing_with_no_live_worker_is_flagged(mdb):
    stale = datetime.now(UTC) - timedelta(seconds=VISIBILITY_TIMEOUT_SECONDS * 4)
    media_id = _clip(mdb, status="processing", claimed_at=stale, worker_id="dead-worker")
    # no heartbeat for dead-worker
    findings = _by_entity(integrity_service.run_checks(mdb, TENANT), media_id)
    kinds = {f["kind"] for f in findings}
    assert "stuck_processing" in kinds


def test_stuck_processing_with_live_worker_is_not_flagged(mdb):
    stale = datetime.now(UTC) - timedelta(seconds=VISIBILITY_TIMEOUT_SECONDS * 4)
    media_id = _clip(mdb, status="processing", claimed_at=stale, worker_id="live-worker")
    mdb["worker_heartbeats"].insert_one({"_id": "live-worker", "last_heartbeat": datetime.now(UTC)})
    findings = _by_entity(integrity_service.run_checks(mdb, TENANT), media_id)
    assert "stuck_processing" not in _kinds(findings)


def test_pending_handoff_is_flagged(mdb):
    media_id = _clip(mdb, status="analyzed", detection_id="d2", handoff_status="pending")
    _detection(mdb, media_id=media_id, did="d2")
    findings = _by_entity(integrity_service.run_checks(mdb, TENANT), media_id)
    assert "handoff_pending" in _kinds(findings)


def test_lingering_claim_on_analyzed_is_low(mdb):
    media_id = _clip(
        mdb,
        status="analyzed",
        detection_id="d3",
        handoff_status="done",
        claimed_at=datetime.now(UTC),
        worker_id="w9",
    )
    _detection(mdb, media_id=media_id, did="d3")
    findings = {
        f["kind"]: f for f in _by_entity(integrity_service.run_checks(mdb, TENANT), media_id)
    }
    assert "lingering_claim" in findings
    assert findings["lingering_claim"]["severity"] == integrity_service.LOW


def test_detection_scope_mismatch_is_high(mdb):
    # clip in HOUSE, detection claims a different house -> mismatch.
    media_id = _clip(mdb, status="analyzed", detection_id="dm", handoff_status="done")
    did = _detection(mdb, media_id=media_id, house="99999999-0000-0000-0000-0000000000c1", did="dm")
    findings = {f["kind"]: f for f in _by_entity(integrity_service.run_checks(mdb, TENANT), did)}
    assert "detection_scope_mismatch" in findings
    assert findings["detection_scope_mismatch"]["severity"] == integrity_service.HIGH


def test_activity_bucket_scope_mismatch_is_high(mdb):
    # A detection fed a bucket; the bucket's house was tampered to a different one.
    media_id = _clip(mdb, status="analyzed", detection_id="da", handoff_status="done")
    _detection(mdb, media_id=media_id, did="da")
    bad_house = "99999999-0000-0000-0000-0000000000c1"
    hours = [0] * 24
    hours[14] = 1
    _bucket(mdb, house=bad_house, counted=["da"], hours=hours)
    findings = integrity_service.run_checks(mdb, TENANT)
    bucket_id = f"{bad_house}:{ROOM}:2026-06-01"
    mismatches = {f["kind"] for f in _by_entity(findings, bucket_id)}
    assert "activity_scope_mismatch" in mismatches


def test_bucket_count_mismatch_is_low(mdb):
    # sum(hours)=3 but counted has 1 entry -> inconsistency.
    hours = [0] * 24
    hours[10] = 3
    _bucket(mdb, counted=["one"], hours=hours)
    findings = integrity_service.run_checks(mdb, TENANT)
    bucket_id = f"{HOUSE}:{ROOM}:2026-06-01"
    kinds = {f["kind"]: f for f in _by_entity(findings, bucket_id)}
    assert "bucket_count_mismatch" in kinds
    assert kinds["bucket_count_mismatch"]["severity"] == integrity_service.LOW


def test_tenant_scope_narrows_the_scan(mdb):
    # A fault in a different tenant must not surface when scanning TENANT.
    other = "aaaaaaaa-0000-0000-0000-0000000000c1"
    _detection(mdb, media_id=str(uuid.uuid4()), tenant=other)  # orphan in other tenant
    findings = integrity_service.run_checks(mdb, TENANT)
    assert findings == []
    # But an all-tenant scan sees it.
    all_findings = integrity_service.run_checks(mdb, tenant_id=None)
    assert "orphan_detection" in _kinds(all_findings)


def test_scheduler_integrity_job_records_a_report(mdb, pg_url):
    """The scheduler's nightly job runs the scan and records a report row (C3-12 DoD).

    Exercises run_integrity_job end to end: start a running report, scan real Mongo, finish
    with the findings. Verifies the report is 'done' with the planted fault recorded.
    """
    from app.scheduler import run_integrity_job
    from homeai_common import db
    from sqlalchemy import text

    # Plant a high-severity fault: an analyzed clip with no detection_id.
    _clip(mdb, status="analyzed")

    db.configure_db(pg_url)
    try:
        count = run_integrity_job(mdb)
        assert count >= 1
        with db.session_scope() as session:
            row = session.execute(
                text(
                    "SELECT status, findings FROM c3.integrity_reports "
                    "WHERE scope->>'tenant_id' IS NULL "
                    "ORDER BY started_at DESC LIMIT 1"
                )
            ).one()
            assert row.status == "done"
            kinds = {f["kind"] for f in row.findings}
            assert "analyzed_no_detection" in kinds
    finally:
        # Tidy the report rows this test created and reset DB config for other tests.
        with db.session_scope() as session:
            session.execute(
                text("DELETE FROM c3.integrity_reports WHERE scope->>'tenant_id' IS NULL")
            )
        db.dispose_db()
