#!/usr/bin/env python3
"""Master demo seed (P0-10, docs/03_REPO_AND_INFRA.md §7): every component's seed, in order.

Order (03 §7): C4 (tenants, users, settings, contacts, service clients) -> C1 (houses, rooms,
feeds) -> C2 (tenant default alert rules). C3's active model (yamnet 1.0.0) is created by C3's
own migration, so it has no step here. Every step is idempotent, so `make seed` can run any time.

Each step runs inside that service's container (the hosts have no project packages; this script
needs only the standard library): ``alembic upgrade head`` in the running container, then
``python -m app.seed`` in a one-off container with the repo mounted for ``scripts/seed_ids.py``.
Services that are not running are skipped with a warning.

    python3 scripts/seed.py                                  # local stack (make seed)
    python3 scripts/seed.py --only c1,c2
    python3 scripts/seed.py --compose "docker compose -f infra/docker-compose.yml \
        -f infra/docker-compose.prod.yml --profile gateway --profile c3 --profile c1"   # EC2
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSE = (
    "docker compose -f infra/docker-compose.yml --profile c1 --profile c3 --profile gateway"
)


@dataclass(frozen=True)
class Step:
    code: str
    service: str
    what: str


STEPS = (
    Step("c4", "c4-dashboard", "tenants, users, settings, contacts, service clients"),
    Step("c1", "c1-iot", "houses, rooms, camera feeds"),
    Step("c2", "c2-alerts", "tenant default alert rules"),
)


def commands(compose: list[str], step: Step, repo: Path = ROOT) -> list[list[str]]:
    """The two commands of one step: migrate in the running container, then seed."""
    migrate = [*compose, "exec", "-T", step.service, "alembic", "upgrade", "head"]
    seed = [
        *compose, "run", "--rm", "--no-deps", "-T",
        "-v", f"{repo}:/workspace:ro", "-e", "PYTHONPATH=/workspace", "-w", "/app",
        step.service, "python", "-m", "app.seed",
    ]  # fmt: skip
    return [migrate, seed]


def plan(only: set[str] | None, running: set[str]) -> tuple[list[Step], list[Step]]:
    """``(steps to run, steps skipped because their service is not running)``."""
    wanted = [s for s in STEPS if only is None or s.code in only]
    return [s for s in wanted if s.service in running], [
        s for s in wanted if s.service not in running
    ]


def running_services(compose: list[str]) -> set[str]:
    out = subprocess.run(
        [*compose, "ps", "--services", "--status", "running"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed every component's demo data in order.")
    parser.add_argument("--compose", default=DEFAULT_COMPOSE, help="docker compose command line")
    parser.add_argument("--only", help="comma-separated component codes, e.g. c1,c2")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)  # our lines stay in order with the steps' output

    compose = shlex.split(args.compose)
    only = {c.strip().lower() for c in args.only.split(",")} if args.only else None
    try:
        to_run, skipped = plan(only, running_services(compose))
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"[seed] cannot list running services ({exc}); is the stack up?", file=sys.stderr)
        return 1

    failed: list[str] = []
    for step in to_run:
        print(f"[seed] {step.code}: {step.what}")
        for cmd in commands(compose, step):
            if subprocess.run(cmd, cwd=ROOT).returncode != 0:
                failed.append(step.code)
                print(f"[seed] {step.code} failed: {shlex.join(cmd)}", file=sys.stderr)
                break
    for step in skipped:
        print(f"[seed] {step.code}: skipped, {step.service} is not running", file=sys.stderr)
    print("[seed] c3: model yamnet 1.0.0 comes from C3's migration (no seed step)")
    if failed:
        print(f"[seed] failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
