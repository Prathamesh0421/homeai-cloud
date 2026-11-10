#!/usr/bin/env python3
"""Run the C3 integrity check on demand (C3-12).

The nightly scheduler in the worker runs this across all tenants; this manual trigger lets
demo prep and the demo run it without waiting for the clock. It records an integrity_reports
row and prints the findings count by severity. Read-only against the Mongo stores; the only
write is the report row in Postgres.

Usage (inside the compose network, or with host-reachable endpoints):
    python scripts/demo/c3_integrity.py [--tenant-id <uuid>]

Reads MONGO_URL_C3 and DATABASE_URL_C3 from the environment (same vars as the service).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

# Make homeai_common and the service package importable from a source checkout.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "homeai_common"))
sys.path.insert(0, str(ROOT / "services" / "c3_data"))

from app.scheduler import run_integrity_job  # noqa: E402
from app.services import integrity_service  # noqa: E402
from app.settings import get_settings  # noqa: E402
from homeai_common import db  # noqa: E402
from homeai_common.mongo import get_mongo_db  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the C3 integrity check on demand.")
    parser.add_argument(
        "--tenant-id",
        default=None,
        help="Narrow the check to one tenant (default: all tenants).",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.mongo_url:
        print("ERROR: MONGO_URL_C3 is not set", file=sys.stderr)
        return 1

    mongo = get_mongo_db(settings.mongo_url)

    if args.tenant_id:
        # Per-tenant scan without the report row (handy for a quick look).
        findings = integrity_service.run_checks(mongo, tenant_id=args.tenant_id)
    else:
        # All-tenant run via the scheduler's job so it records an integrity_reports row.
        if not settings.database_url:
            print("ERROR: DATABASE_URL_C3 is not set (needed for the report row)", file=sys.stderr)
            return 1
        db.configure_db(settings.database_url, reader_url=settings.database_reader_url)
        try:
            findings_count = run_integrity_job(mongo)
        finally:
            db.dispose_db()
        print(f"[integrity] recorded a report with {findings_count} finding(s)")
        return 0

    by_severity = Counter(f["severity"] for f in findings)
    print(f"[integrity] {len(findings)} finding(s): {dict(by_severity)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
