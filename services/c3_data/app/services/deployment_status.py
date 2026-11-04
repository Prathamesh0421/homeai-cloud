"""Deployment status for the Model Management panel (C3-08, docs §3.1).

Aggregates the live deployment picture: the active model, worker heartbeats, Mongo queue
depth, recent throughput, and worker-reported p95 latency.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo.database import Database


def build_deployment_status(db: Database, active_model: dict | None) -> dict[str, Any]:
    events = db["media_events"]
    heartbeats = list(db["worker_heartbeats"].find({}))

    now = datetime.now(UTC)
    hour_ago = now - timedelta(hours=1)

    queue = {
        "queued": events.count_documents({"status": "queued"}),
        "processing": events.count_documents({"status": "processing"}),
        "failed": events.count_documents({"status": "failed"}),
        "analyzed_last_hour": events.count_documents(
            {"status": "analyzed", "claimed_at": {"$gte": hour_ago}}
        ),
    }

    # Throughput: analyzed in the last hour, per minute.
    throughput_per_min = round(queue["analyzed_last_hour"] / 60.0, 2)

    # p95 latency across workers' reported averages (best-effort; per-clip p95 lives in eval).
    latencies = [hb.get("avg_latency_ms", 0) for hb in heartbeats if hb.get("avg_latency_ms")]
    p95_latency_ms = int(max(latencies)) if latencies else 0

    workers = [
        {
            "worker_id": hb.get("_id"),
            "hostname": hb.get("hostname"),
            "model_id": hb.get("model_id"),
            "model_version": hb.get("model_version"),
            "last_heartbeat": hb.get("last_heartbeat"),
            "processed": hb.get("processed", 0),
            "failed": hb.get("failed", 0),
            "avg_latency_ms": hb.get("avg_latency_ms", 0),
        }
        for hb in heartbeats
    ]

    return {
        "active_model": active_model,
        "workers": workers,
        "queue": queue,
        "throughput_per_min": throughput_per_min,
        "p95_latency_ms": p95_latency_ms,
    }
