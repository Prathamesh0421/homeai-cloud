#!/usr/bin/env python3
"""Run the C3 activity-baseline job on demand (C3-11 follow-up 1a).

``run_baseline_job`` recomputes ``baseline_mean``/``baseline_std`` and the ``anomaly_score`` for
every house/room with a bucket today. Nothing schedules it yet (the shared nightly scheduler
lands in 8c), so this manual trigger lets demo prep and the demo populate baselines without
waiting for a clock. The job is idempotent (it ``$set``s computed values), so re-running it is
harmless.

Usage (inside the compose network, or with host-reachable endpoints):
    python scripts/demo/c3_baseline.py [--as-of 2026-07-01T12:00:00Z]

Reads MONGO_URL_C3 from the environment (same var as the service).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

# Make homeai_common and the service package importable from a source checkout.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "homeai_common"))
sys.path.insert(0, str(ROOT / "services" / "c3_data"))

from app.services.activity_service import run_baseline_job  # noqa: E402
from app.settings import get_settings  # noqa: E402
from homeai_common.mongo import get_mongo_db  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the C3 activity-baseline job on demand.")
    parser.add_argument(
        "--as-of",
        default=None,
        help="ISO-8601 UTC instant to compute the baseline as of (default: now).",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.mongo_url:
        print("ERROR: MONGO_URL_C3 is not set", file=sys.stderr)
        return 1

    as_of = None
    if args.as_of:
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")).astimezone(UTC)

    mongo = get_mongo_db(settings.mongo_url)
    updated = run_baseline_job(mongo, as_of=as_of)
    print(f"[baseline] updated {updated} house/room pair(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
