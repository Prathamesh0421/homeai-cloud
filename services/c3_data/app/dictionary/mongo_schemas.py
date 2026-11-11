"""Declared shapes of the MongoDB collections in the data dictionary (C3-13, docs §4.7).

MongoDB has no ``information_schema``, so unlike the Postgres schemas (reflected live) the
Mongo collection shapes are hand-authored here and kept in step with the repository docstrings
(``detection_repo``, ``activity_repo``, ``heartbeat_repo``, ``media_event_repo``).

Ownership (docs §2.2):
  - C3 owns ``ai_detections``, ``activity_patterns``, ``worker_heartbeats``.
  - C1 owns ``media_events``; C3 only writes the processing fields, so the dictionary lists it
    under C1 and marks the C3-written fields.

The ``internal`` flag marks a field that exists in the stored document but is NOT part of the
public API surface — notably ``activity_patterns.counted``, the idempotency ledger of
detection ids (Rev4 §6). An internal field is reflected (so the dictionary is honest about what
is stored) but flagged so the dictionary does not present it as a public field.
"""

from __future__ import annotations

from typing import TypedDict


class MongoField(TypedDict, total=False):
    name: str
    type: str
    internal: bool


class MongoCollection(TypedDict):
    name: str
    store: str
    owner_component: str
    fields: list[MongoField]


def _f(name: str, type_: str, *, internal: bool = False) -> MongoField:
    field: MongoField = {"name": name, "type": type_}
    if internal:
        field["internal"] = True
    return field


# Each collection's fields in document order. Types are the logical Mongo/BSON types.
MONGO_COLLECTIONS: list[MongoCollection] = [
    {
        "name": "ai_detections",
        "store": "mongo",
        "owner_component": "c3",
        "fields": [
            _f("_id", "string (uuid)"),
            _f("media_id", "string (uuid)"),
            _f("tenant_id", "string (uuid)"),
            _f("house_id", "string (uuid)"),
            _f("room_id", "string (uuid)"),
            _f("model", "object {model_id, name, version}"),
            _f("labels", "array<object {label, confidence, source_class, start_s, end_s}>"),
            _f("top_label", "string"),
            _f("top_confidence", "double"),
            _f("detected_at", "date (UTC)"),
        ],
    },
    {
        "name": "activity_patterns",
        "store": "mongo",
        "owner_component": "c3",
        "fields": [
            _f("_id", "string ('<house>:<room>:<yyyy-mm-dd>')"),
            _f("tenant_id", "string (uuid)"),
            _f("house_id", "string (uuid)"),
            _f("room_id", "string (uuid)"),
            _f("date", "string (yyyy-mm-dd, UTC)"),
            _f("hours", "array<int>[24]"),
            # The idempotency ledger: detection ids already folded into this bucket. Stored but
            # never returned by the API (Rev4 §6) — mark internal.
            _f("counted", "array<string (uuid)>", internal=True),
            _f("baseline_mean", "array<double>[24]"),
            _f("baseline_std", "array<double>[24]"),
            _f("anomaly_score", "double | null"),
            _f("last_activity_at", "date (UTC)"),
        ],
    },
    {
        "name": "worker_heartbeats",
        "store": "mongo",
        "owner_component": "c3",
        "fields": [
            _f("_id", "string (worker_id)"),
            _f("hostname", "string"),
            _f("model_id", "string (uuid) | null"),
            _f("model_version", "string | null"),
            _f("started_at", "date (UTC)"),
            _f("last_heartbeat", "date (UTC, TTL 600s)"),
            _f("processed", "int"),
            _f("failed", "int"),
            _f("avg_latency_ms", "double"),
        ],
    },
    {
        # C1 owns the collection; C3 writes only the processing fields. Listed here so the
        # dictionary is complete, with owner_component c1.
        "name": "media_events",
        "store": "mongo",
        "owner_component": "c1",
        "fields": [
            _f("_id", "string (media_id)"),
            _f("tenant_id", "string (uuid)"),
            _f("house_id", "string (uuid)"),
            _f("room_id", "string (uuid)"),
            _f("feed_id", "string (uuid)"),
            _f("media_kind", "string"),
            _f("s3", "object {bucket, key, size, content_type}"),
            _f("captured_at", "date (UTC)"),
            _f("uploaded_at", "date (UTC)"),
            # C3-written processing fields (docs §4.1).
            _f("status", "string (queued|processing|analyzed|failed) [C3]"),
            _f("attempts", "int [C3]"),
            _f("claimed_at", "date (UTC) | null [C3]"),
            _f("worker_id", "string | null [C3]"),
            _f("error", "string | null [C3]"),
            _f("detection_id", "string (uuid) | null [C3]"),
            _f("handoff_status", "string (none|pending|done) [C3]"),
        ],
    },
]
