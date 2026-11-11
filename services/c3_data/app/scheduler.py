"""The one C3 background scheduler (C3-12, Rev4 §5).

A single APScheduler ``BackgroundScheduler`` in the worker process drives all three nightly
jobs: the activity baseline (``run_baseline_job``, deferred here from 8b), the integrity check
across all tenants, and the backup to S3 (C3-14). Keeping them on one scheduler is deliberate —
there is exactly one scheduler story in C3, and it lives here.

The jobs are idempotent (baseline ``$set``s computed values; integrity is read-only + records a
report row; backup writes date-keyed S3 objects), so a missed-then-caught-up fire is harmless.
When scaling to several workers set ``C3_SCHEDULER_ENABLED=false`` on the extra workers so the
jobs fire on exactly one instance.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from homeai_common import db, mongo

from app.jobs.backup import run_backup_job
from app.repositories.integrity_repo import CheckAlreadyRunning, IntegrityRepo
from app.services import integrity_service
from app.services.activity_service import run_baseline_job
from app.settings import Settings

logger = logging.getLogger("c3.scheduler")


def run_integrity_job(mongo_db) -> int:
    """Nightly all-tenant integrity scan; record one report row. Returns findings count.

    Uses its own write session (c3_app) for the report row. ``CheckAlreadyRunning`` means an
    operator-triggered all-tenant check is in flight, so the nightly run yields and logs.
    """
    with db.session_scope() as session:  # commit on success, rollback on error
        repo = IntegrityRepo(session)
        try:
            report_id = repo.start({"tenant_id": None}, requested_by=None)
        except CheckAlreadyRunning:
            logger.info("integrity job skipped: a check is already running")
            return 0
        session.commit()  # make the running row visible before the (slow) scan

        try:
            findings = integrity_service.run_checks(mongo_db, tenant_id=None)
            repo.finish(report_id, findings)
        except Exception:
            repo.fail(report_id)
            raise
        logger.info("integrity job done", extra={"findings": len(findings)})
        return len(findings)


def build_scheduler(settings: Settings, mongo_db) -> BackgroundScheduler:
    """Create (but do not start) the scheduler with both nightly jobs registered."""
    scheduler = BackgroundScheduler(timezone="UTC")

    scheduler.add_job(
        run_baseline_job,
        trigger="cron",
        hour=settings.baseline_job_hour,
        minute=0,
        args=[mongo_db],
        id="baseline",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_integrity_job,
        trigger="cron",
        hour=settings.integrity_job_hour,
        minute=0,
        args=[mongo_db],
        id="integrity",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # Nightly backup to S3 (C3-14). Takes settings (s3 bucket, db + mongo URIs); it shells out to
    # pg_dump/mongodump with the URI directly. Only registered when S3 looks configured.
    scheduler.add_job(
        run_backup_job,
        trigger="cron",
        hour=settings.backup_job_hour,
        minute=0,
        args=[settings],
        id="backup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler


def start_scheduler(settings: Settings) -> BackgroundScheduler | None:
    """Build and start the scheduler for a worker, or None if disabled/unconfigured.

    Returns the running scheduler so the caller can shut it down on stop.
    """
    if not settings.scheduler_enabled:
        logger.info("scheduler disabled (C3_SCHEDULER_ENABLED=false)")
        return None
    if not settings.mongo_url:
        logger.warning("scheduler not started: MONGO_URL_C3 unset")
        return None

    mongo_db = mongo.get_mongo_db(settings.mongo_url)
    scheduler = build_scheduler(settings, mongo_db)
    scheduler.start()
    logger.info(
        "scheduler started",
        extra={
            "baseline_hour": settings.baseline_job_hour,
            "integrity_hour": settings.integrity_job_hour,
            "backup_hour": settings.backup_job_hour,
        },
    )
    return scheduler
