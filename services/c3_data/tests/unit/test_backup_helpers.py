"""C3-14: pure backup helpers — URL shaping and tool guard (no infra, Rev4 §7)."""

from __future__ import annotations

import pytest
from app.jobs import backup as backup_job


def test_libpq_url_strips_driver_suffix():
    assert (
        backup_job.libpq_url("postgresql+psycopg://c3_app:devpass@host:5432/homeai")
        == "postgresql://c3_app:devpass@host:5432/homeai"
    )


def test_libpq_url_preserves_percent_encoded_password():
    # A % in a Secrets Manager password is percent-encoded in the URI; libpq decodes it, so we
    # must pass it through unchanged (NOT %%-escape it like the Alembic ConfigParser path).
    url = "postgresql+psycopg://c3_app:p%2Fass%25word@host:5432/homeai"
    out = backup_job.libpq_url(url)
    assert out == "postgresql://c3_app:p%2Fass%25word@host:5432/homeai"
    assert "%%" not in out  # no ConfigParser-style escaping


def test_libpq_url_no_driver_is_unchanged():
    assert backup_job.libpq_url("postgresql://u:p@host:5432/db") == "postgresql://u:p@host:5432/db"


def test_require_tools_raises_when_missing(monkeypatch):
    monkeypatch.setattr(backup_job.shutil, "which", lambda _t: None)
    with pytest.raises(backup_job.BackupToolMissing):
        backup_job._require_tools("pg_dump")


def test_c3_collections_include_activity_patterns_not_media_events():
    # activity_patterns is the newest and the easy one to miss; media_events is C1-owned.
    assert "activity_patterns" in backup_job.C3_COLLECTIONS
    assert "ai_detections" in backup_job.C3_COLLECTIONS
    assert "worker_heartbeats" in backup_job.C3_COLLECTIONS
    assert "media_events" not in backup_job.C3_COLLECTIONS


def test_media_event_fields_are_only_c3_processing_fields():
    # The exported field set must be exactly C3's processing fields — no C1-owned fields.
    assert set(backup_job.MEDIA_EVENT_C3_FIELDS) == {
        "status",
        "attempts",
        "claimed_at",
        "worker_id",
        "error",
        "detection_id",
        "handoff_status",
    }
    for c1_field in ("house_id", "feed_id", "tenant_id", "s3", "media_kind"):
        assert c1_field not in backup_job.MEDIA_EVENT_C3_FIELDS
