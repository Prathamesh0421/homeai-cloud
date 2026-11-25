#!/usr/bin/env python3
"""API load test for S-7 (docs/05 §7, docs/08 §4): p50/p95 and error rate per endpoint.

Runs ``--concurrency`` clients against each endpoint for ``--duration`` seconds, through the
gateway or the ALB (``--base-url``), with real tokens from C4:

- ``alerts``     ``GET /api/v1/alerts?status=open`` as the house owner (C2 list + C1 names)
- ``evaluate``   ``POST /api/v1/alerts/evaluate`` as ``c3-worker`` (C2 rule path: Mongo
                 detection, C1 house, C4 settings, rules)
- ``dashboard``  ``GET /api/v1/dashboard/summary`` as the house owner (C4 fan-out to C1-C3)

``evaluate`` never raises alerts or sends email: it re-sends one stored detection that C2
already answered ``no_alert`` (each call still runs the full rule path; only a detection with
an alert short-cuts to ``duplicate``). Without ``--detection-id`` the script uploads
``demo_clips/cough.wav`` to Maple St (no YAMNet label -> ``no_rule_match``) and waits for C3.
It stops if that detection would alert.

    python scripts/perf/api_load.py --base-url http://44.226.166.194 --copies 1
    python scripts/perf/api_load.py --endpoints alerts,evaluate --concurrency 20 --duration 60 \
        --copies 2 --csv results/api_load_2copies.csv

Secrets come from the environment (DEMO_PASSWORD, SERVICE_CLIENT_SECRET_C3,
SERVICE_CLIENT_SECRET_DEVICE); the dev defaults only work on a local stack. The printed rows
match the S-7 table in docs/RESULTS.md.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import math
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))

from stack import Stack, StackError  # noqa: E402

OWNER = "owner.maple@acme.test"
LOW_CLIP = "cough.wav"  # YAMNet labels nothing in it (21 Nov), so C2 answers no_rule_match


@dataclass
class Endpoint:
    name: str
    label: str  # as in docs/RESULTS.md
    method: str
    path: str
    token: str
    json: dict | None = None
    ok: tuple[int, ...] = (200,)


@dataclass
class Result:
    endpoint: str
    latencies_ms: list[float] = field(default_factory=list)
    statuses: Counter = field(default_factory=Counter)
    errors: int = 0
    elapsed_s: float = 0.0


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile (q in 0-100); 0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q / 100 * len(ordered)) - 1)]


def evaluate_body(detection: dict) -> dict:
    return {
        "detection_id": detection["id"],
        "media_id": detection["media_id"],
        "house_id": detection["house_id"],
        "room_id": detection.get("room_id"),
        "top_label": detection["top_label"],
        "top_confidence": detection["top_confidence"],
        "labels": detection.get("labels", []),
        "detected_at": detection["detected_at"],
    }


def no_alert_detection(stack: Stack, detection_id: str | None) -> dict:
    owner = stack.user_token(OWNER)
    if detection_id:
        detection = stack.call("GET", f"/api/v1/records/detections/{detection_id}", owner)["data"]
    else:
        print(f"[api_load] uploading {LOW_CLIP} to Maple Kitchen Mic, waiting for C3 ...")
        media_id = stack.upload_clip("maple_kitchen_mic", LOW_CLIP)
        detection = stack.wait_for_detection(media_id, owner, within=120)
    r = stack.evaluate(detection)
    body = r.json().get("data", {}) if r.status_code < 500 else {}
    if r.status_code != 200 or body.get("decision") != "no_alert":
        raise StackError(
            f"detection {detection['id']} ({detection.get('top_label')} "
            f"{detection.get('top_confidence')}) is not a no_alert detection: {r.status_code} "
            f"{r.text[:300]}; pass --detection-id of one that is"
        )
    print(f"[api_load] evaluate uses detection {detection['id']} ({body.get('reason')})")
    return detection


async def run_endpoint(
    client: httpx.AsyncClient, ep: Endpoint, concurrency: int, duration: float
) -> Result:
    result = Result(ep.name)
    deadline = time.monotonic() + duration
    headers = {"Authorization": f"Bearer {ep.token}"}

    async def worker() -> None:
        while time.monotonic() < deadline:
            start = time.perf_counter()
            try:
                r = await client.request(ep.method, ep.path, headers=headers, json=ep.json)
                status = r.status_code
            except httpx.HTTPError as exc:
                status = type(exc).__name__
            result.latencies_ms.append((time.perf_counter() - start) * 1000)
            result.statuses[status] += 1
            if status not in ep.ok:
                result.errors += 1

    started = time.monotonic()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    result.elapsed_s = time.monotonic() - started
    return result


def row(ep: Endpoint, res: Result, copies: str, concurrency: int) -> str:
    n = len(res.latencies_ms)
    rate = f"{res.errors / n:.1%}" if n else "—"
    return (
        f"| `{ep.label}` | {copies} | {concurrency} | {n} | {percentile(res.latencies_ms, 50):.0f}"
        f" | {percentile(res.latencies_ms, 95):.0f} | {rate} |"
    )


async def main_async(args: argparse.Namespace) -> int:
    stack = Stack(args.base_url, os.environ.get("DEMO_PASSWORD", "Demo!2026"))
    try:
        owner = stack.user_token(OWNER)
        endpoints = {
            "alerts": Endpoint(
                "alerts", "GET /alerts", "GET", "/api/v1/alerts?status=open&page_size=20", owner
            ),
            "dashboard": Endpoint(
                "dashboard", "GET /dashboard/summary", "GET", "/api/v1/dashboard/summary", owner
            ),
        }
        if "evaluate" in args.endpoints:
            detection = no_alert_detection(stack, args.detection_id)
            endpoints["evaluate"] = Endpoint(
                "evaluate",
                "POST /alerts/evaluate",
                "POST",
                "/api/v1/alerts/evaluate",
                stack.service_token("c3-worker"),
                json=evaluate_body(detection),
            )
    finally:
        stack.close()

    limits = httpx.Limits(
        max_connections=args.concurrency, max_keepalive_connections=args.concurrency
    )
    results: list[tuple[Endpoint, Result]] = []
    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"), timeout=args.timeout, limits=limits
    ) as client:
        for name in args.endpoints:
            ep = endpoints[name]
            print(
                f"[api_load] {ep.label}: {args.concurrency} clients for {args.duration:.0f} s ..."
            )
            res = await run_endpoint(client, ep, args.concurrency, args.duration)
            others = {k: v for k, v in res.statuses.items() if k not in ep.ok}
            print(
                f"[api_load]   {len(res.latencies_ms)} requests, "
                f"{len(res.latencies_ms) / res.elapsed_s:.1f}/s"
                + (f", non-OK: {dict(others)}" if others else "")
            )
            results.append((ep, res))

    print("\n| Endpoint | Copies | Concurrency | Requests | p50 (ms) | p95 (ms) | Error rate |")
    print("|---|---|---|---|---|---|---|")
    for ep, res in results:
        print(row(ep, res, args.copies, args.concurrency))

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(
                [
                    "endpoint",
                    "copies",
                    "concurrency",
                    "requests",
                    "rps",
                    "p50_ms",
                    "p95_ms",
                    "p99_ms",
                    "max_ms",
                    "errors",
                    "statuses",
                ]
            )
            for ep, res in results:
                lat = res.latencies_ms
                w.writerow(
                    [
                        ep.label,
                        args.copies,
                        args.concurrency,
                        len(lat),
                        f"{len(lat) / res.elapsed_s:.1f}",
                        f"{percentile(lat, 50):.1f}",
                        f"{percentile(lat, 95):.1f}",
                        f"{percentile(lat, 99):.1f}",
                        f"{max(lat, default=0):.1f}",
                        res.errors,
                        dict(res.statuses),
                    ]
                )
        print(f"\n[api_load] wrote {args.csv}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--base-url", default=os.environ.get("HOMEAI_API_URL", "http://localhost:8080"))
    p.add_argument(
        "--endpoints",
        default="alerts,evaluate,dashboard",
        type=lambda s: [e.strip() for e in s.split(",") if e.strip()],
        help="comma list of alerts, evaluate, dashboard (run one after another)",
    )
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--duration", type=float, default=30, help="seconds per endpoint")
    p.add_argument("--timeout", type=float, default=10)
    p.add_argument("--copies", default="1", help="label for the Copies column (1, 2, ALB ...)")
    p.add_argument("--detection-id", help="a stored detection C2 answers no_alert for")
    p.add_argument("--csv", type=Path, help="also write per-endpoint stats here")
    args = p.parse_args(argv)
    unknown = set(args.endpoints) - {"alerts", "evaluate", "dashboard"}
    if unknown:
        p.error(f"unknown endpoints: {', '.join(sorted(unknown))}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(main_async(args))
    except StackError as exc:
        print(f"[api_load] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
