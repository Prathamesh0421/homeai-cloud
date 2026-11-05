"""Detection statistics (C3-10, contract §4.6).

``GET /detections/stats?group_by=top_label|day|house`` over C3's ``ai_detections``, scoped by
tenant/house. Returns buckets ``[{key, count}]`` plus ``meta.total_clips``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pymongo.database import Database

from app.services.record_scope import RecordScope

GROUP_FIELDS = {
    "top_label": "$top_label",
    "house": "$house_id",
    # day: formatted from detected_at below.
}


def detection_stats(
    mongo: Database,
    scope: RecordScope,
    group_by: str,
    *,
    from_: datetime | None,
    to: datetime | None,
    house_id: str | None,
) -> tuple[list[dict[str, Any]], int]:
    col = mongo["ai_detections"]
    match: dict[str, Any] = scope.mongo_filter()
    if house_id:
        match["house_id"] = house_id
    if from_ or to:
        window: dict[str, Any] = {}
        if from_:
            window["$gte"] = from_
        if to:
            window["$lt"] = to
        match["detected_at"] = window

    if group_by == "day":
        group_id = {"$dateToString": {"format": "%Y-%m-%d", "date": "$detected_at"}}
    else:
        group_id = GROUP_FIELDS[group_by]

    pipeline = [
        {"$match": match},
        {"$group": {"_id": group_id, "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
    ]
    buckets = [
        {"key": doc["_id"] if doc["_id"] is not None else "none", "count": doc["count"]}
        for doc in col.aggregate(pipeline)
    ]
    if group_by == "day":
        buckets.sort(key=lambda b: b["key"])
    total_clips = col.count_documents(match)
    return buckets, total_clips
