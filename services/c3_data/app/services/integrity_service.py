"""Data-integrity checks across the C3 stores (C3-12, Rev4 §5).

The pipeline can leave faults behind: a detection whose clip vanished, a clip marked
``analyzed`` with no detection, a clip stuck ``processing`` after its worker died, a handoff
that never reached C2, or a tenant/house mismatch between a record and its clip. This module
scans for each and returns findings with a severity; it does not mutate data (the operator
requeues or re-sends separately). It is read-only and safe to run on every tenant nightly.

Each check has a matching *plant helper* in ``tests``/the demo so the checks and the faults
they look for cannot drift apart.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo.database import Database

from app.repositories.detection_repo import COLLECTION as DET_COLLECTION
from app.repositories.heartbeat_repo import COLLECTION as HB_COLLECTION
from app.repositories.media_event_repo import COLLECTION as EV_COLLECTION
from app.repositories.media_event_repo import VISIBILITY_TIMEOUT_SECONDS

logger = logging.getLogger("c3.integrity")

ACTIVITY_COLLECTION = "activity_patterns"

# Severities.
HIGH = "high"
MEDIUM = "medium"
LOW = "low"

# A processing clip is "stuck" once it is older than a few visibility timeouts with no live
# worker holding it: one timeout is a normal reclaim window, so we use a generous multiple to
# avoid flagging a clip that is simply mid-reclaim.
STUCK_PROCESSING_SECONDS = VISIBILITY_TIMEOUT_SECONDS * 3


def _finding(kind: str, severity: str, entity_id: str, detail: dict[str, Any]) -> dict[str, Any]:
    return {"kind": kind, "severity": severity, "entity_id": entity_id, "detail": detail}


def _scope_filter(tenant_id: str | None) -> dict:
    return {"tenant_id": tenant_id} if tenant_id else {}


def run_checks(
    mongo: Database, tenant_id: str | None = None, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Run every integrity check for a tenant (or all tenants if ``tenant_id`` is None).

    Returns a flat list of findings. Read-only.
    """
    now = (now or datetime.now(UTC)).astimezone(UTC)
    events = mongo[EV_COLLECTION]
    detections = mongo[DET_COLLECTION]
    heartbeats = mongo[HB_COLLECTION]
    patterns = mongo[ACTIVITY_COLLECTION]
    scope = _scope_filter(tenant_id)

    findings: list[dict[str, Any]] = []

    # Live workers: a heartbeat present at all means the worker is live (the TTL index removes
    # dead ones after 600 s). We judge "stuck" by claim age, not just presence.
    live_worker_ids = {hb["_id"] for hb in heartbeats.find({}, {"_id": 1})}

    # 1. Orphan detection: a detection whose media_id has no media_events doc.
    media_ids = {ev["_id"] for ev in events.find(scope, {"_id": 1})}
    for det in detections.find(scope, {"_id": 1, "media_id": 1, "house_id": 1, "tenant_id": 1}):
        if det.get("media_id") not in media_ids:
            findings.append(
                _finding(
                    "orphan_detection",
                    MEDIUM,
                    det["_id"],
                    {"media_id": det.get("media_id"), "house_id": det.get("house_id")},
                )
            )

    # 2. analyzed clip with no detection_id — the Prathamesh fault class (6dddfcc): HIGH.
    for ev in events.find(
        {
            **scope,
            "status": "analyzed",
            "$or": [{"detection_id": None}, {"detection_id": {"$exists": False}}],
        },
        {"_id": 1, "house_id": 1},
    ):
        findings.append(
            _finding("analyzed_no_detection", HIGH, ev["_id"], {"house_id": ev.get("house_id")})
        )

    # 3. clip stuck in processing past the visibility window with no live worker.
    stuck_before = now - timedelta(seconds=STUCK_PROCESSING_SECONDS)
    for ev in events.find(
        {**scope, "status": "processing", "claimed_at": {"$lt": stuck_before}},
        {"_id": 1, "worker_id": 1, "claimed_at": 1},
    ):
        if ev.get("worker_id") not in live_worker_ids:
            findings.append(
                _finding(
                    "stuck_processing",
                    MEDIUM,
                    ev["_id"],
                    {
                        "worker_id": ev.get("worker_id"),
                        "claimed_at": _iso(ev.get("claimed_at")),
                    },
                )
            )

    # 4. a handoff that never reached done (analyzed clip still pending).
    for ev in events.find(
        {**scope, "status": "analyzed", "handoff_status": "pending"},
        {"_id": 1, "detection_id": 1},
    ):
        findings.append(
            _finding("handoff_pending", MEDIUM, ev["_id"], {"detection_id": ev.get("detection_id")})
        )

    # 5. lingering claim fields on an analyzed clip (mark_analyzed now clears them, so this
    #    catches rows written before that fix or by another path).
    for ev in events.find(
        {
            **scope,
            "status": "analyzed",
            "$or": [
                {"claimed_at": {"$exists": True, "$ne": None}},
                {"worker_id": {"$exists": True, "$ne": None}},
            ],
        },
        {"_id": 1, "worker_id": 1},
    ):
        findings.append(
            _finding("lingering_claim", LOW, ev["_id"], {"worker_id": ev.get("worker_id")})
        )

    # 6. tenant_id/house_id mismatch between a detection and its clip, AND between an activity
    #    bucket and its clip. 8b's rollup copies tenant_id/house_id from the detection into the
    #    bucket, so a mismatched detection propagates into activity; check both.
    ev_scope: dict[str, dict] = {
        ev["_id"]: {"tenant_id": ev.get("tenant_id"), "house_id": ev.get("house_id")}
        for ev in events.find(scope, {"_id": 1, "tenant_id": 1, "house_id": 1})
    }
    for det in detections.find(scope, {"_id": 1, "media_id": 1, "tenant_id": 1, "house_id": 1}):
        clip = ev_scope.get(det.get("media_id"))
        if clip is None:
            continue  # orphan already reported above
        if det.get("tenant_id") != clip["tenant_id"] or det.get("house_id") != clip["house_id"]:
            findings.append(
                _finding(
                    "detection_scope_mismatch",
                    HIGH,
                    det["_id"],
                    {
                        "media_id": det.get("media_id"),
                        "detection": {
                            "tenant_id": det.get("tenant_id"),
                            "house_id": det.get("house_id"),
                        },
                        "clip": clip,
                    },
                )
            )

    # activity bucket vs clip: a bucket's tenant/house must match the detections that fed it.
    # We compare the bucket's (tenant_id, house_id) against each counted detection's clip.
    det_by_id = {d["_id"]: d for d in detections.find(scope, {"_id": 1, "media_id": 1})}
    for bucket in patterns.find(scope, {"_id": 1, "tenant_id": 1, "house_id": 1, "counted": 1}):
        for did in bucket.get("counted", []):
            det = det_by_id.get(did)
            if det is None:
                continue
            clip = ev_scope.get(det.get("media_id"))
            if clip is None:
                continue
            if (
                bucket.get("tenant_id") != clip["tenant_id"]
                or bucket.get("house_id") != clip["house_id"]
            ):
                findings.append(
                    _finding(
                        "activity_scope_mismatch",
                        HIGH,
                        bucket["_id"],
                        {
                            "detection_id": did,
                            "bucket": {
                                "tenant_id": bucket.get("tenant_id"),
                                "house_id": bucket.get("house_id"),
                            },
                            "clip": clip,
                        },
                    )
                )
                break  # one finding per bucket is enough

    # 7. (optional, cheap) bucket consistency: sum(hours) must equal len(counted).
    for bucket in patterns.find(scope, {"_id": 1, "hours": 1, "counted": 1}):
        hours_sum = sum(bucket.get("hours", []))
        counted_len = len(bucket.get("counted", []))
        if hours_sum != counted_len:
            findings.append(
                _finding(
                    "bucket_count_mismatch",
                    LOW,
                    bucket["_id"],
                    {"hours_sum": hours_sum, "counted": counted_len},
                )
            )

    logger.info(
        "integrity check done",
        extra={"tenant_id": tenant_id, "findings": len(findings)},
    )
    return findings


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value
