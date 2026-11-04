#!/usr/bin/env python3
"""Enqueue a demo clip for the C3 worker (stub for C1; docs §1.1, contract §4.1).

Uploads a local audio clip to S3 under the C1 key layout and inserts a ``media_events``
document with ``status=queued`` so the worker picks it up. Dev/demo only.

Usage (inside compose network, or with host-reachable endpoints):
    python scripts/demo/c3_enqueue.py --clip demo_clips/glass_break.wav \
        --house-id <uuid> --room-id <uuid> [--tenant-id <uuid>] [--feed-id <uuid>]

Reads connection settings from the environment (same vars as the services):
    S3_BUCKET, AWS_REGION, AWS_ENDPOINT_URL (LocalStack), MONGO_URL_C3
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Make homeai_common importable from a source checkout.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "homeai_common"))

sys.path.insert(0, str(ROOT / "scripts"))

import seed_ids  # noqa: E402
from homeai_common.mongo import get_mongo_db  # noqa: E402
from homeai_common.s3 import s3_client  # noqa: E402

TENANT_ACME = seed_ids.TENANTS["acme"]  # seed Acme Care tenant (scripts/seed_ids.py)


def s3_key(tenant_id: str, house_id: str, feed_id: str, media_id: str, ext: str) -> str:
    now = datetime.now(UTC)
    return f"tenants/{tenant_id}/houses/{house_id}/feeds/{feed_id}/{now:%Y/%m/%d}/{media_id}.{ext}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enqueue a demo clip for the C3 worker.")
    parser.add_argument("--clip", required=True, help="Path to a local audio clip")
    parser.add_argument("--house-id", required=True)
    parser.add_argument("--room-id", default=None)
    parser.add_argument("--tenant-id", default=TENANT_ACME)
    parser.add_argument("--feed-id", default=None)
    args = parser.parse_args(argv)

    clip = Path(args.clip)
    if not clip.exists():
        print(f"ERROR: clip not found: {clip}", file=sys.stderr)
        return 1

    bucket = os.environ.get("S3_BUCKET", "homeai-local")
    region = os.environ.get("AWS_REGION", "us-west-2")
    endpoint = os.environ.get("AWS_ENDPOINT_URL") or None
    mongo_url = os.environ.get("MONGO_URL_C3") or (
        "mongodb://c3_app:devpass@localhost:27017/homeai?authSource=homeai"
    )

    media_id = str(uuid.uuid4())
    feed_id = args.feed_id or str(uuid.uuid4())
    ext = clip.suffix.lstrip(".") or "wav"
    content_type = mimetypes.guess_type(clip.name)[0] or "audio/wav"
    key = s3_key(args.tenant_id, args.house_id, feed_id, media_id, ext)

    body = clip.read_bytes()
    s3 = s3_client(region, endpoint)
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    print(f"[enqueue] uploaded s3://{bucket}/{key} ({len(body)} bytes)")

    now = datetime.now(UTC)
    doc = {
        "_id": media_id,
        "tenant_id": args.tenant_id,
        "house_id": args.house_id,
        "room_id": args.room_id,
        "feed_id": feed_id,
        "media_kind": "audio",
        "s3": {"bucket": bucket, "key": key, "size": len(body), "content_type": content_type},
        "captured_at": now,
        "uploaded_at": now,
        "client_clip_id": f"demo-{media_id[:8]}",
        "status": "queued",
        "attempts": 0,
        "claimed_at": None,
        "worker_id": None,
        "error": None,
        "detection_id": None,
        "handoff_status": "none",
    }
    db = get_mongo_db(mongo_url)
    db["media_events"].insert_one(doc)
    print(f"[enqueue] inserted media_events _id={media_id} status=queued")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
