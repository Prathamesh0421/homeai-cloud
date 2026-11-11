#!/usr/bin/env python3
"""Fake a C3 detection and send it to C2, as the C3 worker does (DEMO_MODE fallback; C2 plan §10).

1. Inserts an ``ai_detections`` document (contract 02 §4.2) into Mongo as C3 would.
2. Gets a ``c3-worker`` service token from C4 (scope ``alerts:evaluate``), unless ``--token``.
3. Calls ``POST /api/v1/alerts/evaluate`` (contract 02 §4.3) and prints C2's decision.

    python scripts/demo/c2_fake_detection.py --label glass_break --conf 0.78 --house maple
    python scripts/demo/c2_fake_detection.py --resend <detection_id>     # idempotency: duplicate
    ... --media-id <clip media_id>    # a clip already in C1 (Clip Library): the alert can play it

Environment (defaults suit `make up` from the host):
    HOMEAI_API_URL               gateway, default http://localhost:8080 (C2 and C4 behind Caddy)
    MONGO_URL_C3                 C3's writer, default mongodb://c3_app:devpass@localhost:27017/homeai
    SERVICE_CLIENT_SECRET_C3     c3-worker secret, default dev-c3-secret
Refuses to run when ENV is prod/production unless DEMO_MODE=1 (the EC2 demo).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/ for seed_ids
import seed_ids

# Home labels, contract 02 §3.
LABELS = (
    "smoke_alarm",
    "distress_sound",
    "glass_break",
    "fall_indicator",
    "cough",
    "speech",
    "dog",
)
# Seeded active model (C3 migration 0002).
MODEL = {"model_id": "a0000000-0000-4000-8000-000000000001", "name": "yamnet", "version": "1.0.0"}
DEFAULT_ROOM = {"fall_indicator": "Bathroom", "glass_break": "Entryway", "smoke_alarm": "Kitchen"}


def resolve_room(house_alias: str | None, room: str) -> str:
    """A seeded room name (any case) in a seeded house, or a room UUID."""
    names = {n.lower(): n for n in seed_ids.ROOM_NAMES}
    if house_alias and room.lower() in names:
        return seed_ids.room_id(house_alias, names[room.lower()])
    try:
        return str(uuid.UUID(room))
    except ValueError:
        raise ValueError(
            f"unknown room {room!r}: use one of {', '.join(seed_ids.ROOM_NAMES)} or a room UUID"
        ) from None


def body_of(r: httpx.Response) -> str:
    """JSON pretty-printed, or the raw text (e.g. an HTML 502 from the gateway)."""
    try:
        return json.dumps(r.json(), indent=2)
    except ValueError:
        return r.text[:500]


def build_detection(
    *,
    label: str,
    confidence: float,
    house: str,
    room: str | None,
    now: datetime | None = None,
    media_id: str | None = None,
) -> dict[str, Any]:
    """An ``ai_detections`` document shaped exactly like C3's (contract §4.2)."""
    house_id = seed_ids.house_id(house)
    alias = next((a for a, h in seed_ids.HOUSES.items() if h[0] == house_id), None)
    room_id = resolve_room(alias, room or DEFAULT_ROOM.get(label, "Living"))
    labels = [{"label": label, "confidence": round(confidence, 3), "source_class": "demo"}]
    return {
        "_id": str(uuid.uuid4()),
        # A real C1 clip (its media_id from the Clip Library) lets Alert Detail and the alert
        # view play it (C2-11); a made-up one shows "The recording is not available".
        "media_id": media_id or str(uuid.uuid4()),
        "tenant_id": seed_ids.tenant_of(house_id),
        "house_id": house_id,
        "room_id": room_id,
        "model": MODEL,
        "labels": labels,
        "top_label": label,
        "top_confidence": round(confidence, 3),
        "detected_at": now or datetime.now(UTC),
    }


def evaluate_payload(doc: dict[str, Any]) -> dict[str, Any]:
    """The body C3 sends to C2 (contract §4.3)."""
    return {
        "detection_id": doc["_id"],
        "media_id": doc["media_id"],
        "house_id": doc["house_id"],
        "room_id": doc["room_id"],
        "top_label": doc["top_label"],
        "top_confidence": doc["top_confidence"],
        "labels": [{"label": x["label"], "confidence": x["confidence"]} for x in doc["labels"]],
        "detected_at": doc["detected_at"].astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }


def service_token(http: httpx.Client, secret: str) -> str:
    r = http.post(
        "/api/v1/auth/service-token",
        json={"client_id": "c3-worker", "client_secret": secret, "scope": ["alerts:evaluate"]},
    )
    if r.status_code != 200:
        raise SystemExit(
            f"C4 refused the c3-worker service token ({r.status_code}): {r.text[:300]}"
        )
    return r.json()["data"]["token"]


def main(
    argv: list[str] | None = None,
    *,
    http: httpx.Client | None = None,
    detections: Any = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", choices=LABELS)
    parser.add_argument("--conf", type=float, default=0.78, help="top confidence (0-1)")
    parser.add_argument("--house", default="maple", help="maple | oak | pine | house UUID")
    parser.add_argument("--room", help="room name (Kitchen, Bathroom, ...) or room UUID")
    parser.add_argument("--resend", metavar="DETECTION_ID", help="send a stored detection again")
    parser.add_argument("--token", help="service token with alerts:evaluate (skips C4)")
    parser.add_argument(
        "--media-id", help="a clip's media_id in C1, so the alert can play it (default: made up)"
    )
    args = parser.parse_args(argv)
    if not args.resend and not args.label:
        parser.error("--label is required (or --resend DETECTION_ID)")
    if not 0 <= args.conf <= 1:
        parser.error("--conf must be between 0 and 1")
    if args.media_id:
        try:
            args.media_id = str(uuid.UUID(args.media_id))
        except ValueError:
            parser.error("--media-id must be a clip's UUID (C1 Clip Library)")
    production = os.environ.get("ENV", "local").lower() in {"prod", "production"}
    if production and os.environ.get("DEMO_MODE") != "1":
        print("refusing to fake detections with ENV=production and DEMO_MODE off", file=sys.stderr)
        return 2

    if detections is None:
        url = os.environ.get("MONGO_URL_C3", "mongodb://c3_app:devpass@localhost:27017/homeai")
        detections = MongoClient(url, tz_aware=True).get_default_database()["ai_detections"]
    if args.resend:
        doc = detections.find_one({"_id": args.resend})
        if doc is None:
            print(f"no detection {args.resend} in ai_detections", file=sys.stderr)
            return 1
    else:
        try:
            doc = build_detection(
                label=args.label,
                confidence=args.conf,
                house=args.house,
                room=args.room,
                media_id=args.media_id,
            )
        except (ValueError, KeyError) as exc:
            parser.error(str(exc).strip("'\""))
        detections.insert_one(doc)
        print(f"detection {doc['_id']} stored ({doc['top_label']} {doc['top_confidence']})")

    http = http or httpx.Client(
        base_url=os.environ.get("HOMEAI_API_URL", "http://localhost:8080"), timeout=10
    )
    token = args.token or service_token(
        http, os.environ.get("SERVICE_CLIENT_SECRET_C3", "dev-c3-secret")
    )
    r = http.post(
        "/api/v1/alerts/evaluate",
        json=evaluate_payload(doc),
        headers={"Authorization": f"Bearer {token}"},
    )
    print(f"C2 answered {r.status_code}: {body_of(r)}")
    print(f"resend with: --resend {doc['_id']}")
    return 0 if r.status_code < 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
