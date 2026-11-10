"""Fixed IDs and row builders for C1 tests (same patterns as scripts/seed_ids.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.models import CameraFeed, FeedConfigVersion, House, Room

TENANT_A = "11111111-0000-0000-0000-000000000001"  # Acme Care
TENANT_B = "11111111-0000-0000-0000-000000000002"  # Sunrise Living
HOUSE_A1 = "22222222-0000-0000-0000-0000000000a1"  # Maple St
HOUSE_A2 = "22222222-0000-0000-0000-0000000000a2"  # Oak Ave
HOUSE_B1 = "22222222-0000-0000-0000-0000000000b1"  # Pine Rd
ROOM_A1_KITCHEN = "33333333-0000-0000-0000-00000000a101"
ROOM_A1_BATH = "33333333-0000-0000-0000-00000000a104"
ROOM_B1_KITCHEN = "33333333-0000-0000-0000-00000000b101"
STAFF_USER = "44444444-0000-0000-0000-000000000004"  # iot@acme.test
OPS_USER = "44444444-0000-0000-0000-000000000001"  # ops@homeai.test
OWNER_USER = "44444444-0000-0000-0000-000000000002"  # owner.maple@acme.test

NOW = datetime(2026, 11, 10, 18, 0, tzinfo=UTC)
DEFAULT_CONFIG = {"capture_interval_s": 30, "sensitivity": "medium", "network_label": None}


def uid() -> str:
    return str(uuid.uuid4())


def make_house(house_id: str | None = None, tenant_id: str = TENANT_A, **kw) -> House:
    return House(
        house_id=house_id or uid(),
        tenant_id=tenant_id,
        name=kw.pop("name", f"House {uuid.uuid4().hex[:6]}"),
        timezone=kw.pop("timezone", "America/Los_Angeles"),
        **kw,
    )


def make_room(house_id: str, room_id: str | None = None, **kw) -> Room:
    return Room(
        room_id=room_id or uid(),
        house_id=house_id,
        name=kw.pop("name", f"Room {uuid.uuid4().hex[:6]}"),
        room_type=kw.pop("room_type", "other"),
        **kw,
    )


def make_feed(
    house: House, room_id: str | None = None, feed_id: str | None = None, **kw
) -> CameraFeed:
    config = kw.pop("config", dict(DEFAULT_CONFIG))
    return CameraFeed(
        feed_id=feed_id or uid(),
        tenant_id=house.tenant_id,
        house_id=house.house_id,
        room_id=room_id,
        name=kw.pop("name", f"Feed {uuid.uuid4().hex[:6]}"),
        media_kind=kw.pop("media_kind", "audio"),
        status=kw.pop("status", "provisioned"),
        is_enabled=kw.pop("is_enabled", False),
        connectivity_status=kw.pop("connectivity_status", "unknown"),
        config=config,
        config_version=kw.pop("config_version", 1),
        consecutive_failures=kw.pop("consecutive_failures", 0),
        **kw,
    )


def make_version(feed: CameraFeed, version: int = 1, **kw) -> FeedConfigVersion:
    return FeedConfigVersion(
        feed_id=feed.feed_id,
        version=version,
        capture_interval_s=kw.pop("capture_interval_s", feed.config["capture_interval_s"]),
        sensitivity=kw.pop("sensitivity", feed.config["sensitivity"]),
        network_label=kw.pop("network_label", feed.config.get("network_label")),
        created_by=kw.pop("created_by", STAFF_USER),
        **kw,
    )
