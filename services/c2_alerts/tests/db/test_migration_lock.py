"""S-3: copies starting together run `alembic upgrade head` one after another (advisory lock)."""

from __future__ import annotations

import threading

from alembic import command
from alembic.config import Config
from app.jobs.lock import MIGRATION_LOCK
from sqlalchemy import text

from tests.db.conftest import SERVICE_DIR


def _upgrade_in_thread() -> tuple[threading.Thread, list[BaseException]]:
    # As the container does it: env.py opens its own connection (DATABASE_URL_C2).
    cfg = Config()  # no ini file, so the test's logging config is left alone
    cfg.set_main_option("script_location", str(SERVICE_DIR / "alembic"))
    errors: list[BaseException] = []

    def run() -> None:
        try:
            command.upgrade(cfg, "head")
        except BaseException as exc:  # pragma: no cover - reported by the assert below
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, errors


def _lock_held(pg_engine) -> bool:
    with pg_engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
                    " AND (classid::bigint << 32) + objid::bigint = :k AND granted"
                ),
                {"k": MIGRATION_LOCK},
            ).scalar()
        )


def test_upgrade_waits_for_another_copy_then_releases(pg_engine):
    with pg_engine.connect() as other_copy:
        other_copy.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK})
        other_copy.commit()
        thread, errors = _upgrade_in_thread()
        thread.join(timeout=2)
        assert thread.is_alive(), "upgrade ran while another copy held the migration lock"
        other_copy.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK})
        other_copy.commit()
    thread.join(timeout=30)
    assert not thread.is_alive() and errors == []
    assert not _lock_held(pg_engine)  # released after a normal run
