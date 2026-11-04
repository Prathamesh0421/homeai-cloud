"""Runs the jobs with their own sessions and advisory locks; schedules them in the API process.

``JobRunner`` is built in ``create_app`` (``app.state.jobs``). The scheduler calls it every
60 s / 5 min; ``POST /alert-rules/subscriptions/sync`` calls ``sync`` directly. A run whose
lock is held elsewhere returns None (another process is doing it).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from homeai_common import db
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.gateways.c1_house_gateway import C1HouseGateway
from app.gateways.c4_settings_gateway import C4SettingsGateway
from app.gateways.notifier import Notifier
from app.gateways.types import DependencyUnavailableError
from app.jobs.lock import RETRY_LOCK, SYNC_LOCK, advisory_lock
from app.jobs.notification_retry import NotificationRetry, RetryResult
from app.jobs.subscription_sync import SubscriptionSync, SyncResult
from app.services.notification_service import NotificationService
from app.services.quiet_hours import utc_now
from app.services.signed_link import SignedLinkService

logger = logging.getLogger(__name__)

RETRY_EVERY_S = 60
SYNC_EVERY_S = 300

SessionScope = Callable[[], AbstractContextManager[Session]]


@contextmanager
def reader_scope() -> Iterator[Session]:
    """``c2_reader`` session (c4 contacts, c1 houses); unavailable if not configured."""
    try:
        db.get_engine(db.READER)
    except RuntimeError as exc:
        raise DependencyUnavailableError("c2_reader", "DATABASE_READER_URL_C2 not set") from exc
    with db.session_scope(db.READER) as session:
        yield session


@dataclass
class JobRunner:
    notifier: Notifier
    links: SignedLinkService
    lock_engine: Callable[[], Engine] = field(default=lambda: db.get_engine())
    primary: SessionScope = field(default=db.session_scope)
    reader: SessionScope = field(default=reader_scope)
    clock: Callable[[], datetime] = utc_now

    def retry(self) -> RetryResult | None:
        with advisory_lock(self.lock_engine(), RETRY_LOCK) as held:
            if not held:
                logger.debug("notification retry is running elsewhere")
                return None
            with self.primary() as session, self.reader() as reader:
                service = NotificationService(
                    session=session,
                    notifier=self.notifier,
                    links=self.links,
                    contacts=C4SettingsGateway(reader),
                    houses=C1HouseGateway(reader),
                    clock=self.clock,
                )
                return NotificationRetry(service).run()

    def sync(self, house_id: str | None = None) -> SyncResult | None:
        with advisory_lock(self.lock_engine(), SYNC_LOCK) as held:
            if not held:
                logger.debug("subscription sync is running elsewhere")
                return None
            with self.reader() as reader:
                return SubscriptionSync(C4SettingsGateway(reader), self.notifier).run(house_id)


def _logged(name: str, fn: Callable[[], object]) -> Callable[[], None]:
    def run() -> None:
        try:
            fn()
        except Exception as exc:  # a failing run must not kill the scheduler thread
            logger.exception("job failed", extra={"job": name, "error": type(exc).__name__})

    return run


def start_scheduler(runner: JobRunner) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(
        timezone="UTC",
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 30},
    )
    scheduler.add_job(
        _logged("notification_retry", runner.retry),
        "interval",
        seconds=RETRY_EVERY_S,
        id="notification_retry",
    )
    scheduler.add_job(
        _logged("subscription_sync", runner.sync),
        "interval",
        seconds=SYNC_EVERY_S,
        id="subscription_sync",
    )
    scheduler.start()
    logger.info("jobs scheduled", extra={"retry_s": RETRY_EVERY_S, "sync_s": SYNC_EVERY_S})
    return scheduler
