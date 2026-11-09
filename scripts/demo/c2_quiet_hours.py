#!/usr/bin/env python3
"""Set a seeded house's quiet hours for the C2 demo (C2 plan §10.1 step 5) through C4's own code.

Quiet hours hold medium/low alerts (a cough) but not high/critical ones (glass break). C4's
Settings page is not built yet (C4-12), so this sets them the way C4's
``PUT /houses/{id}/settings`` does, keeping the house's enabled services and sensitivity.
Times are the house's local time (seed timezone, e.g. America/Los_Angeles for Maple).

Runs inside the c4-dashboard image, from the repo root: ``make demo-c2-quiet-hours ARGS=...``

    --cover-now [--hours 2]   quiet from 15 minutes ago for 2 hours: the demo is inside it
    --set 22:00-07:00         a fixed window (22:00-07:00 is the seeded one)
    --off                     no quiet hours
    --show                    print the current settings only
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/ for seed_ids
import seed_ids

OPS_USER = seed_ids.USERS["ops@homeai.test"][0]  # recorded as updated_by
LEAD = timedelta(minutes=15)


def house_timezone(house_id: str) -> str:
    return next(h[3] for h in seed_ids.HOUSES.values() if h[0] == house_id)


def window_covering(now: datetime, tz: str, hours: float) -> tuple[str, str]:
    """A quiet window (house-local HH:MM) that started LEAD ago and lasts ``hours``."""
    if not 0 < hours < 24:
        raise ValueError("--hours must be between 0 and 24")
    local = now.astimezone(ZoneInfo(tz)) - LEAD
    start = local.replace(minute=local.minute - local.minute % 5, second=0, microsecond=0)
    end = start + timedelta(hours=hours)
    return start.strftime("%H:%M"), end.strftime("%H:%M")


def parse_window(text: str) -> tuple[str, str]:
    """``"22:00-07:00"`` -> ``("22:00", "07:00")`` (may wrap midnight)."""
    try:
        start, end = (part.strip() for part in text.split("-"))
        for part in (start, end):
            datetime.strptime(part, "%H:%M")
    except ValueError:
        raise ValueError(f"bad window {text!r}: use HH:MM-HH:MM, e.g. 22:00-07:00") from None
    return start, end


def describe(settings) -> str:
    quiet = f"{settings.quiet_start}-{settings.quiet_end}" if settings.quiet_start else "none"
    return f"quiet hours {quiet}, sensitivity {settings.sensitivity}"


def main(argv: list[str] | None = None, *, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--house", default="maple", help="maple | oak | pine | house UUID")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--cover-now", action="store_true")
    mode.add_argument("--set", metavar="HH:MM-HH:MM")
    mode.add_argument("--off", action="store_true")
    mode.add_argument("--show", action="store_true")
    parser.add_argument("--hours", type=float, default=2.0, help="with --cover-now (default 2)")
    args = parser.parse_args(argv)
    try:
        house = seed_ids.house_id(args.house)
        tz = house_timezone(house)
        window = (
            window_covering(now or datetime.now(UTC), tz, args.hours)
            if args.cover_now
            else parse_window(args.set)
            if args.set
            else (None, None)
        )
    except (ValueError, KeyError, StopIteration) as exc:
        parser.error(str(exc).strip("'\"") or f"unknown house {args.house!r}")

    # C4's code, from the c4-dashboard image (PYTHONPATH=/app).
    from app.db.session import session_scope
    from app.schemas.settings import SettingsUpsertRequest
    from app.services import settings_service

    with session_scope() as session:
        current = settings_service.get_settings(session, UUID(house))
        print(f"house {args.house} ({tz}): {describe(current)}")
        if args.show:
            return 0
        payload = SettingsUpsertRequest(
            enabled_services=current.enabled_services,
            quiet_start=window[0],
            quiet_end=window[1],
            sensitivity=current.sensitivity,
        )
        updated = settings_service.upsert_settings(
            session,
            house_id=UUID(house),
            tenant_id=UUID(seed_ids.tenant_of(house)),
            updated_by=UUID(OPS_USER),
            payload=payload,
        )
    print(f"now: {describe(updated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
