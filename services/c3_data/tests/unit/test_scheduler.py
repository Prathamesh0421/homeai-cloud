"""C3-12/14: the one scheduler registers the nightly jobs at the configured UTC hours."""

from __future__ import annotations

from app.scheduler import build_scheduler
from app.settings import Settings


class _FakeMongo:
    def __getitem__(self, _name):
        raise AssertionError("scheduler build must not touch Mongo")


def _settings(**over) -> Settings:
    base = {
        "mongo_url": "mongodb://x/y",
        "scheduler_enabled": True,
        "baseline_job_hour": 2,
        "integrity_job_hour": 3,
        "backup_job_hour": 4,
    }
    base.update(over)
    return Settings(**base)


def test_build_scheduler_registers_baseline_integrity_and_backup():
    scheduler = build_scheduler(_settings(), _FakeMongo())
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {"baseline", "integrity", "backup"}


def test_jobs_use_configured_utc_hours():
    scheduler = build_scheduler(
        _settings(baseline_job_hour=4, integrity_job_hour=5, backup_job_hour=6), _FakeMongo()
    )
    hours = {job.id: str(job.trigger).lower() for job in scheduler.get_jobs()}
    # APScheduler's CronTrigger repr includes the hour field; assert the configured hours appear.
    assert "hour='4'" in hours["baseline"]
    assert "hour='5'" in hours["integrity"]
    assert "hour='6'" in hours["backup"]
    # Timezone is UTC (C3 owns one frame of reference).
    assert "utc" in str(scheduler.timezone).lower()
