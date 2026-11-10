"""Runs the ConnectivityMonitor on APScheduler inside the API process (C1 plan §4.2).

Each run takes a Postgres transaction-level advisory lock on its own connection (same pattern as
C2's jobs), so with several API processes only one updates the feeds at a time.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from homeai_common import db
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.services.connectivity import ConnectivityMonitor, MonitorResult

logger = logging.getLogger(__name__)

# One fixed 64-bit key per job ("C1" + job number).
CONNECTIVITY_LOCK = 0x4331_0000_0001


@contextmanager
def advisory_lock(engine: Engine, key: int) -> Iterator[bool]:
    """Yield True if this caller holds the lock for the block, False if someone else does."""
    with engine.connect() as conn, conn.begin():
        yield bool(conn.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key}).scalar())


def run_once(
    *,
    lock_engine: Callable[[], Engine] = db.get_engine,
    session_scope: Callable[[], AbstractContextManager[Session]] = db.session_scope,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> MonitorResult | None:
    """One monitor pass; None when another process holds the lock."""
    with advisory_lock(lock_engine(), CONNECTIVITY_LOCK) as held:
        if not held:
            logger.debug("connectivity monitor is running elsewhere")
            return None
        with session_scope() as session:
            result = ConnectivityMonitor(session).run(clock())
    if result.unknown or result.online or result.offline:
        logger.info(
            "connectivity monitor updated feeds",
            extra={"unknown": result.unknown, "online": result.online, "offline": result.offline},
        )
    return result


def _safe_run() -> None:
    try:
        run_once()
    except Exception:  # pragma: no cover - logged; the next tick tries again
        logger.exception("connectivity monitor failed")


def start_scheduler(interval_s: int) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(
        timezone="UTC",
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 30},
    )
    scheduler.add_job(_safe_run, "interval", seconds=interval_s, id="connectivity_monitor")
    scheduler.start()
    logger.info("connectivity monitor scheduled", extra={"interval_s": interval_s})
    return scheduler
