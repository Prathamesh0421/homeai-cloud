"""C3-11 (unit): anomaly band boundaries and bucket id (pure logic, no store)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.repositories.activity_repo import BAND_ANOMALOUS, BAND_UNUSUAL, band, bucket_id, day_str


def test_bands():
    assert band(None) == "insufficient_data"
    assert band(0.0) == "normal"
    assert band(BAND_UNUSUAL - 0.001) == "normal"
    assert band(BAND_UNUSUAL) == "unusual"
    assert band(0.45) == "unusual"
    assert band(BAND_ANOMALOUS - 0.001) == "unusual"
    assert band(BAND_ANOMALOUS) == "anomalous"
    assert band(0.9) == "anomalous"


def test_bucket_id_and_day_are_utc():
    # A non-UTC input is normalised to UTC before bucketing.
    from datetime import timedelta, timezone

    pacific = timezone(-timedelta(hours=8))
    # 2026-06-01 23:30 -08:00 == 2026-06-02 07:30 UTC.
    when = datetime(2026, 6, 1, 23, 30, tzinfo=pacific)
    assert day_str(when) == "2026-06-02"
    assert bucket_id("h", "r", when) == "h:r:2026-06-02"


def test_bucket_id_plain_utc():
    when = datetime(2026, 6, 1, 14, 0, tzinfo=UTC)
    assert bucket_id("h", "r", when) == "h:r:2026-06-01"
