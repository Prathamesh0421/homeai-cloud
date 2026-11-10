#!/usr/bin/env python3
"""Device simulator (C1-09): uploads demo clips to one feed every few seconds, like a camera.

Gets a ``device-uploader`` service token (scope ``ingest:write``) from C4, then loops over the
clips and calls C1 ``POST /api/v1/ingest/clip``, printing each response. Stop it with Ctrl-C;
the ConnectivityMonitor then flips the feed to inactive/offline after its capture interval.

    python scripts/device_sim.py --feed-id 66666666-0000-0000-0000-00000000a101 --interval 5
    python scripts/device_sim.py --feed-id <uuid> --clips demo_clips/glass_break.wav --count 1

Environment: ``HOMEAI_API_URL`` (default http://localhost:8080, the Caddy gateway; C4's token
endpoint and C1's ingest are both behind it) and ``SERVICE_CLIENT_SECRET_DEVICE`` (default
``dev-device-secret``). On EC2: ``make demo-c1-sim ARGS="--feed-id <uuid> --interval 5"``.
"""

from __future__ import annotations

import argparse
import glob
import itertools
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

# Make homeai_common importable from a source checkout (it is installed in the service images).
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libs" / "homeai_common"))

from homeai_common.service_client import ServiceTokenProvider  # noqa: E402

CONTENT_TYPES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".mp4": "video/mp4"}
KINDS = {"audio/wav": "audio", "audio/mpeg": "audio", "video/mp4": "video"}


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload demo clips to a C1 feed on a timer.")
    parser.add_argument("--feed-id", required=True, help="target feed (must be enabled)")
    parser.add_argument("--interval", type=float, default=20.0, help="seconds between uploads")
    parser.add_argument(
        "--clips",
        nargs="+",
        default=["demo_clips/*.wav"],
        help="files or globs, uploaded in turn (default demo_clips/*.wav)",
    )
    parser.add_argument("--count", type=int, default=0, help="stop after N uploads (0 = forever)")
    parser.add_argument(
        "--base-url", default=os.environ.get("HOMEAI_API_URL", "http://localhost:8080")
    )
    parser.add_argument(
        "--c4-url", default=None, help="C4 for the token, if not behind --base-url (e.g. :8004)"
    )
    parser.add_argument(
        "--secret", default=os.environ.get("SERVICE_CLIENT_SECRET_DEVICE", "dev-device-secret")
    )
    return parser.parse_args(argv)


def expand(patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern)) or ([pattern] if Path(pattern).exists() else [])
        files.extend(Path(m) for m in matches if Path(m).suffix.lower() in CONTENT_TYPES)
    return files


def upload(client: httpx.Client, base_url: str, token: str, feed_id: str, clip: Path, n: int):
    content_type = CONTENT_TYPES[clip.suffix.lower()]
    now = datetime.now(UTC)
    return client.post(
        f"{base_url}/api/v1/ingest/clip",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "feed_id": feed_id,
            "media_kind": KINDS[content_type],
            "captured_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "client_clip_id": f"sim-{feed_id[:8]}-{now:%H%M%S}-{n}",
        },
        files={"file": (clip.name, clip.read_bytes(), content_type)},
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    clips = expand(args.clips)
    if not clips:
        print(f"no clips found for {args.clips} (run scripts/fetch_demo_clips.sh)", file=sys.stderr)
        return 1
    base_url = args.base_url.rstrip("/")
    tokens = ServiceTokenProvider(
        c4_base_url=(args.c4_url or base_url).rstrip("/"),
        client_id="device-uploader",
        client_secret=args.secret,
        scopes=["ingest:write"],
    )
    print(f"[device-sim] feed {args.feed_id}: {len(clips)} clip(s) every {args.interval:g}s")
    sent = 0
    with httpx.Client(timeout=30.0) as client:
        try:
            for n, clip in enumerate(itertools.cycle(clips), start=1):
                try:
                    resp = upload(client, base_url, tokens.token(), args.feed_id, clip, n)
                    body = resp.json()
                    detail = body.get("data") or body.get("error")
                    print(f"[device-sim] #{n} {clip.name} -> {resp.status_code} {detail}")
                except httpx.HTTPError as exc:
                    print(f"[device-sim] #{n} {clip.name} -> request failed: {exc}")
                sent += 1
                if args.count and sent >= args.count:
                    break
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n[device-sim] stopped; the feed goes offline after its capture interval")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
