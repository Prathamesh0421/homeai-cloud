"""Activity patterns: idempotent hourly rollup + baseline (C3-11, docs §2.2, §4.5; Rev3 §6.2).

The rollup folds a detection into a per-house/room/day document keyed by ``detection_id`` so
applying it twice equals once. This is the whole point: retries, the 120 s visibility-timeout
reclaim, ``finish_existing``, and force re-classify all replay the tail of the pipeline, and a
plain ``$inc`` would double-count. We instead guard the increment on the detection id not
already being folded into that bucket.

Document (docs §2.2):
  {_id:"<house>:<room>:<yyyy-mm-dd>", tenant_id, house_id, room_id, date,
   hours:[24 ints], counted:[detection_id, ...] (internal, not returned by the API),
   baseline_mean:[24], baseline_std:[24], anomaly_score, last_activity_at}

Time is UTC everywhere: the hour bucket and the 28-day baseline window are computed in UTC
(Rev3 §6.2). The UI converts for display; the backend owns one frame of reference.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from pymongo import ReturnDocument
from pymongo.collection import Collection

COLLECTION = "activity_patterns"

BASELINE_WINDOW_DAYS = 28
# Baseline cold start: with fewer than this many days of history the std is unstable and the
# anomaly score is noise, so we suppress the band (Rev3 §6.2).
MIN_BASELINE_DAYS = 14

# Anomaly bands (docs §4.5).
BAND_UNUSUAL = 0.30
BAND_ANOMALOUS = 0.60


def bucket_id(house_id: str, room_id: str, when: datetime) -> str:
    return f"{house_id}:{room_id}:{when.astimezone(UTC):%Y-%m-%d}"


def day_str(when: datetime) -> str:
    return f"{when.astimezone(UTC):%Y-%m-%d}"


class ActivityRepo:
    def __init__(self, collection: Collection):
        self.collection = collection

    def rollup(self, detection: dict) -> bool:
        """Fold one detection into its house/room/day bucket, idempotent by detection_id.

        Returns True if it counted (first time for this detection_id), False if it was a replay.
        room_id may be missing on a detection; bucket it under "none" so rollups never drop.
        """
        detected_at = detection["detected_at"]
        if isinstance(detected_at, str):
            detected_at = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
        detected_at = detected_at.astimezone(UTC)

        house_id = detection["house_id"]
        room_id = detection.get("room_id") or "none"
        hour = detected_at.hour
        did = detection["_id"]
        bid = bucket_id(house_id, room_id, detected_at)

        # Ensure the day document exists with a zeroed 24-hour array (no-op if already there).
        self.collection.update_one(
            {"_id": bid},
            {
                "$setOnInsert": {
                    "tenant_id": detection.get("tenant_id"),
                    "house_id": house_id,
                    "room_id": room_id,
                    "date": day_str(detected_at),
                    "hours": [0] * 24,
                    "counted": [],
                }
            },
            upsert=True,
        )

        # Conditionally count: only when this detection_id is not already folded in. The filter
        # on counted != did makes a replay match nothing, so hours[h] is incremented exactly once.
        res = self.collection.update_one(
            {"_id": bid, "counted": {"$ne": did}},
            {
                "$inc": {f"hours.{hour}": 1},
                "$addToSet": {"counted": did},
                "$set": {"last_activity_at": detected_at},
            },
        )
        return res.modified_count == 1

    def get(self, house_id: str, room_id: str, date: str) -> dict | None:
        return self.collection.find_one({"_id": f"{house_id}:{room_id}:{date}"})

    def list_for(self, house_id: str, room_id: str | None, dates: list[str]) -> list[dict]:
        q: dict = {"house_id": house_id, "date": {"$in": dates}}
        if room_id:
            q["room_id"] = room_id
        return list(self.collection.find(q).sort("date", -1))

    # -- baseline + anomaly -------------------------------------------------
    def compute_baseline(self, house_id: str, room_id: str, as_of: datetime) -> dict | None:
        """Recompute baseline_mean/std over the trailing 28 days and the anomaly score for today.

        Cold start: if fewer than MIN_BASELINE_DAYS days of history exist, store the baseline but
        leave anomaly_score None (band suppressed) so a new house is not flagged on normal use.
        Returns the updated today document, or None if there is no activity to score.
        """
        as_of = as_of.astimezone(UTC)
        today = day_str(as_of)
        window_dates = [
            day_str(as_of - timedelta(days=d)) for d in range(1, BASELINE_WINDOW_DAYS + 1)
        ]
        history = list(
            self.collection.find(
                {"house_id": house_id, "room_id": room_id, "date": {"$in": window_dates}}
            )
        )
        n_days = len(history)

        mean = [0.0] * 24
        std = [0.0] * 24
        if n_days:
            for h in range(24):
                vals = [doc.get("hours", [0] * 24)[h] for doc in history]
                m = sum(vals) / n_days
                mean[h] = round(m, 3)
                var = sum((v - m) ** 2 for v in vals) / n_days
                std[h] = round(math.sqrt(var), 3)

        today_doc = self.collection.find_one({"_id": f"{house_id}:{room_id}:{today}"})
        if today_doc is None:
            return None

        update: dict = {"baseline_mean": mean, "baseline_std": std}
        if n_days >= MIN_BASELINE_DAYS:
            counts = today_doc.get("hours", [0] * 24)
            # anomaly = mean over hours of min(1, |count - mean| / (3*std + 1))  (docs §4.5)
            score = (
                sum(min(1.0, abs(counts[h] - mean[h]) / (3 * std[h] + 1)) for h in range(24)) / 24
            )
            update["anomaly_score"] = round(score, 4)
        else:
            update["anomaly_score"] = None  # band suppressed during cold start

        return self.collection.find_one_and_update(
            {"_id": f"{house_id}:{room_id}:{today}"},
            {"$set": update},
            return_document=ReturnDocument.AFTER,
        )


def band(anomaly_score: float | None) -> str:
    """Map a score to a band label (docs §4.5); 'insufficient_data' during cold start."""
    if anomaly_score is None:
        return "insufficient_data"
    if anomaly_score >= BAND_ANOMALOUS:
        return "anomalous"
    if anomaly_score >= BAND_UNUSUAL:
        return "unusual"
    return "normal"
