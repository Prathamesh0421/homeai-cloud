#!/usr/bin/env python3
"""Run a C3 backup to S3 on demand (C3-14).

The nightly scheduler runs this at ``C3_BACKUP_JOB_HOUR`` (04:00 UTC default); this manual
trigger lets demo prep take a backup without waiting for the clock. It dumps Postgres schema c3
and the C3-owned Mongo collections (incl. activity_patterns) plus C3's fields of media_events,
and uploads them under ``backups/<date>/``. Idempotent per date (re-running overwrites the day's
objects).

Needs pg_dump/mongodump on PATH (present in the c3-data image). Reads DATABASE_URL_C3,
MONGO_URL_C3, S3_BUCKET, AWS_* from the environment.

Usage (inside the compose network / c3-data image):
    python scripts/demo/c3_backup.py [--as-of 2026-07-01]
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "homeai_common"))
sys.path.insert(0, str(ROOT / "services" / "c3_data"))

from app.jobs.backup import run_backup_job  # noqa: E402
from app.settings import get_settings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a C3 backup to S3 on demand.")
    parser.add_argument("--as-of", default=None, help="ISO-8601 UTC date to label the backup.")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.database_url or not settings.mongo_url:
        print("ERROR: DATABASE_URL_C3 and MONGO_URL_C3 must be set", file=sys.stderr)
        return 1

    as_of = None
    if args.as_of:
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")).astimezone(UTC)

    keys = run_backup_job(settings, as_of=as_of)
    print(f"[backup] wrote: {', '.join(keys.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
