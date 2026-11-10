"""C1 seed: fixed IDs from scripts/seed_ids.py, idempotent."""

from __future__ import annotations

from app.models import CameraFeed, FeedConfigVersion, House, Room
from app.seed import seed
from sqlalchemy import func, select

from tests.factories import HOUSE_A1, ROOM_A1_BATH, TENANT_A

MAPLE_KITCHEN_MIC = "66666666-0000-0000-0000-00000000a101"
MAPLE_NURSERY_MIC = "66666666-0000-0000-0000-00000000a104"
MAPLE_GARAGE_CAM = "66666666-0000-0000-0000-00000000a103"


def count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_seed_creates_houses_rooms_feeds_once(session):
    first = seed(session)
    assert first == {"houses": 3, "rooms": 15, "feeds": 7}
    assert seed(session) == {"houses": 0, "rooms": 0, "feeds": 0}
    assert count(session, House) == 3
    assert count(session, Room) == 15
    assert count(session, CameraFeed) == 7
    assert count(session, FeedConfigVersion) == 7


def test_seed_rows_match_contract_ids(session):
    seed(session)
    maple = session.get(House, HOUSE_A1)
    assert (maple.name, maple.tenant_id, maple.timezone) == (
        "Maple St",
        TENANT_A,
        "America/Los_Angeles",
    )
    assert session.get(Room, ROOM_A1_BATH).name == "Bathroom"

    mic = session.get(CameraFeed, MAPLE_KITCHEN_MIC)
    assert (mic.is_enabled, mic.media_kind, mic.status) == (True, "audio", "provisioned")
    nursery = session.get(CameraFeed, MAPLE_NURSERY_MIC)
    assert (nursery.is_enabled, nursery.room_id) == (False, None)
    garage = session.get(CameraFeed, MAPLE_GARAGE_CAM)
    assert (garage.status, garage.connectivity_status) == ("inactive", "offline")
