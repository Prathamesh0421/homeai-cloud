"""``worker_heartbeats`` writer (MongoDB; docs §2.2).

One document per worker (``_id = worker_id``), upserted on each heartbeat. A TTL index on
``last_heartbeat`` (created by app.db.mongo_indexes) removes dead workers after 10 minutes so
the deployment panel reflects only live workers.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pymongo.collection import Collection

COLLECTION = "worker_heartbeats"


class HeartbeatRepo:
    def __init__(self, collection: Collection):
        self.collection = collection

    def beat(
        self,
        *,
        worker_id: str,
        hostname: str,
        model_id: str | None,
        model_version: str | None,
        started_at: datetime,
        processed: int,
        failed: int,
        avg_latency_ms: float,
    ) -> None:
        self.collection.update_one(
            {"_id": worker_id},
            {
                "$set": {
                    "hostname": hostname,
                    "model_id": model_id,
                    "model_version": model_version,
                    "started_at": started_at,
                    "last_heartbeat": datetime.now(UTC),
                    "processed": processed,
                    "failed": failed,
                    "avg_latency_ms": round(avg_latency_ms, 1),
                }
            },
            upsert=True,
        )
