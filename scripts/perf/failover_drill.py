#!/usr/bin/env python3
"""Failover drill for S-8 (docs/08 §4): stop one copy of a service under load.

Needs the scaled stack (S-1) with two copies of the service behind Caddy (S-2):

    docker compose -f infra/docker-compose.yml -f infra/docker-compose.scale.yml \\
      --profile c1 --profile c3 --profile gateway up -d --scale c1-iot=2 ...

Runs ``--concurrency`` clients against one read endpoint of the service through the gateway for
``--duration`` seconds. At ``--stop-at`` seconds it runs ``docker stop`` on one copy (SIGTERM,
then SIGKILL after ``--stop-timeout``), or ``docker kill`` with ``--kill`` (a crash). It reports
the client error rate (HTTP 5xx or a failed request) before and after the stop, and the recovery
time: from the stop command to the last failed request (0 if none failed). The stopped copy is
started again at the end unless ``--leave-stopped``.

    python scripts/perf/failover_drill.py --service c1-iot
    python scripts/perf/failover_drill.py --service c1-iot --kill --duration 60

Endpoints: c1-iot ``GET /feeds`` (IoT staff), c2-alerts ``GET /alerts?status=open`` (owner),
c3-data ``GET /models`` (cloud staff), c4-dashboard ``GET /dashboard/summary`` (owner).
``--ingest`` (c1-iot) loads with ``POST /ingest/clip`` as the device uploader instead: HTTP clients
retry a GET on a dropped keep-alive connection by themselves, never a POST, so this is the case
the gateway's retry (S-2) has to cover.
c3-worker has no HTTP endpoint (drill it with clips: scripts/perf/clip_to_alert.py).
The printed row matches the S-8 table in docs/RESULTS.md.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
sys.path.insert(0, str(ROOT / "scripts"))

import seed_ids  # noqa: E402
from stack import DEMO_CLIPS, Stack  # noqa: E402

# service -> (path, user that may call it)
ENDPOINTS = {
    "c1-iot": ("/api/v1/feeds?page_size=25", "iot@acme.test"),
    "c2-alerts": ("/api/v1/alerts?status=open", "owner.maple@acme.test"),
    "c3-data": ("/api/v1/models", "ops@homeai.test"),
    "c4-dashboard": ("/api/v1/dashboard/summary", "owner.maple@acme.test"),
}


@dataclass
class Sample:
    t: float  # seconds since the load started (request start)
    ms: float
    status: int  # 0 = the request itself failed (connection reset, timeout)

    @property
    def failed(self) -> bool:
        return self.status == 0 or self.status >= 500


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q / 100 * len(ordered)) - 1)]


def copies(project: str, service: str) -> list[str]:
    out = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            f"label=com.docker.compose.service={service}",
            "--format",
            "{{.Names}}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    return sorted(out)


async def client(send, t0: float, end: float, samples: list[Sample]) -> None:
    while time.monotonic() < end:
        start = time.monotonic()
        try:
            r = await send()
            status = r.status_code
        except httpx.HTTPError:
            status = 0
        samples.append(Sample(start - t0, (time.monotonic() - start) * 1000, status))


async def drill(args: argparse.Namespace) -> int:
    path, user = ENDPOINTS[args.service]
    if args.ingest:
        if args.service != "c1-iot":
            print("--ingest only applies to c1-iot")
            return 2
        path, user = "/api/v1/ingest/clip", "device-uploader"
    running = copies(args.project, args.service)
    if len(running) < 2:
        print(f"need >= 2 running copies of {args.service}, found {running}: scale it first")
        return 2
    victim = running[-1]
    stack = Stack(args.base_url, args.password)
    token = stack.service_token(user) if args.ingest else stack.user_token(user)
    stack.close()
    headers = {"Authorization": f"Bearer {token}"}
    # Ingest: the same client_clip_id every time, so only the first POST stores a clip (and C3
    # analyses one clip); the rest return duplicate: true after the auth, feed and Mongo lookups.
    clip = (DEMO_CLIPS / "silence.wav").read_bytes() if args.ingest else b""
    form = {
        "feed_id": seed_ids.FEEDS["maple_kitchen_mic"][0],
        "media_kind": "audio",
        "captured_at": "2026-11-28T00:00:00Z",
        "client_clip_id": f"s8-drill-{int(time.time())}",
    }

    samples: list[Sample] = []
    limits = httpx.Limits(max_connections=args.concurrency)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=10, limits=limits) as http:
        t0 = time.monotonic()
        end = t0 + args.duration

        def send():
            if args.ingest:
                files = {"file": ("silence.wav", clip, "audio/wav")}
                return http.post(path, headers=headers, data=form, files=files)
            return http.get(path, headers=headers)

        load = [
            asyncio.create_task(client(send, t0, end, samples)) for _ in range(args.concurrency)
        ]
        await asyncio.sleep(args.stop_at)
        cmd = (
            ["docker", "kill", victim]
            if args.kill
            else ["docker", "stop", "-t", str(args.stop_timeout), victim]
        )
        stopped_at = time.monotonic() - t0
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL)
        await proc.wait()
        stop_took = time.monotonic() - t0 - stopped_at
        await asyncio.gather(*load)

    method = "POST" if args.ingest else "GET"
    before = [s for s in samples if s.t < stopped_at]
    after = [s for s in samples if s.t >= stopped_at]
    failed_after = [s for s in after if s.failed]
    recovery = max((s.t + s.ms / 1000 for s in failed_after), default=stopped_at) - stopped_at
    statuses = Counter(s.status for s in samples)

    def rate(xs: list[Sample]) -> str:
        bad = sum(x.failed for x in xs)
        return f"{bad}/{len(xs)} ({100 * bad / len(xs):.2f} %)" if xs else "0/0"

    how = "docker kill" if args.kill else f"docker stop -t {args.stop_timeout}"
    print(
        f"{args.service}: {len(running)} copies, stopped {victim} at t={stopped_at:.1f}s ({how}, took {stop_took:.1f}s)"
    )
    print(
        f"load: {method} {path} as {user}, {args.concurrency} clients, {args.duration}s, {len(samples)} requests"
    )
    print(f"statuses: {dict(sorted(statuses.items()))}  (0 = request failed)")
    print(
        f"errors before stop: {rate(before)}   after stop: {rate(after)}   overall: {rate(samples)}"
    )
    print(
        f"p50/p95 ms before: {percentile([s.ms for s in before], 50):.0f}/{percentile([s.ms for s in before], 95):.0f}"
        f"   after: {percentile([s.ms for s in after], 50):.0f}/{percentile([s.ms for s in after], 95):.0f}"
    )
    print(f"recovery: {recovery:.2f}s (stop command -> last failed request; 0 = no failures)")
    print("\nRESULTS.md row:")
    print(
        f"| {args.service} (1 of {len(running)}) | {args.concurrency} clients `{method} {path.split('?')[0]}`, "
        f"{len(samples)} req / {args.duration}s | {rate(samples)} | {recovery:.1f} s | {how} at t={stopped_at:.0f}s |"
    )

    if not args.leave_stopped:
        subprocess.run(["docker", "start", victim], check=True, capture_output=True)
        print(f"\nstarted {victim} again")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--service", required=True, choices=sorted(ENDPOINTS))
    p.add_argument("--base-url", default="http://localhost:8080")
    p.add_argument(
        "--password", default=None, help="demo password (default: DEMO_PASSWORD or the dev value)"
    )
    p.add_argument("--project", default="homeai", help="docker compose project name")
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--duration", type=float, default=40)
    p.add_argument("--stop-at", type=float, default=10)
    p.add_argument("--stop-timeout", type=int, default=10, help="docker stop grace period (s)")
    p.add_argument("--kill", action="store_true", help="docker kill instead of a graceful stop")
    p.add_argument("--leave-stopped", action="store_true")
    p.add_argument(
        "--ingest",
        action="store_true",
        help="c1-iot only: load with POST /ingest/clip (a device upload) instead of GET /feeds",
    )
    args = p.parse_args()
    if args.password is None:
        args.password = os.environ.get("DEMO_PASSWORD", "Demo!2026")
    return asyncio.run(drill(args))


if __name__ == "__main__":
    sys.exit(main())
