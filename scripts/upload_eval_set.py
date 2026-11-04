#!/usr/bin/env python3
"""Upload the evaluation dataset to S3 (C3-08, docs §4.4).

Uploads demo clips to ``models/eval/{dataset}/`` with a ``manifest.json`` listing
``[{"file","expected"}]`` so ``POST /models/{id}/evaluate`` can score a model. Dev/demo tool.

Usage:
    python scripts/upload_eval_set.py [--dataset eval-v1] [--clips demo_clips]

Reads S3 settings from the environment: S3_BUCKET, AWS_REGION, AWS_ENDPOINT_URL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libs" / "homeai_common"))

from homeai_common.s3 import s3_client  # noqa: E402

# Demo clip -> expected home label (silence/speech/etc. map to "none" under the default map).
CLIP_EXPECTED = {
    "glass_break.wav": "glass_break",
    "dog.wav": "dog",
    "smoke_alarm.wav": "smoke_alarm",
    "silence.wav": "none",
    "speech.wav": "none",
    "cough.wav": "none",
    "scream.wav": "none",
    "thud.wav": "none",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload the C3 evaluation dataset to S3.")
    parser.add_argument("--dataset", default="eval-v1")
    parser.add_argument("--clips", default="demo_clips")
    args = parser.parse_args(argv)

    clips_dir = Path(args.clips)
    if not clips_dir.exists():
        print(f"ERROR: clips dir not found: {clips_dir}", file=sys.stderr)
        return 1

    bucket = os.environ.get("S3_BUCKET", "homeai-local")
    region = os.environ.get("AWS_REGION", "us-west-2")
    endpoint = os.environ.get("AWS_ENDPOINT_URL") or None
    s3 = s3_client(region, endpoint)

    prefix = f"models/eval/{args.dataset}"
    manifest: list[dict] = []
    for name, expected in CLIP_EXPECTED.items():
        path = clips_dir / name
        if not path.exists():
            print(f"[eval] skip missing clip: {name}", file=sys.stderr)
            continue
        s3.put_object(Bucket=bucket, Key=f"{prefix}/{name}", Body=path.read_bytes())
        manifest.append({"file": name, "expected": expected})
        print(f"[eval] uploaded {name} (expected={expected})")

    s3.put_object(
        Bucket=bucket,
        Key=f"{prefix}/manifest.json",
        Body=json.dumps(manifest).encode("utf-8"),
        ContentType="application/json",
    )
    print(f"[eval] wrote manifest with {len(manifest)} clips to s3://{bucket}/{prefix}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
