"""C1 demo reset: rehearsal leftovers go, seed rows come back in their seed state."""

from __future__ import annotations

from datetime import UTC, datetime

from app.demo_reset import reset
from app.models import CameraFeed, FeedConfigVersion, House, Room
from app.seed import seed
from sqlalchemy import func, select

from tests.factories import HOUSE_A1, TENANT_A, make_feed, make_house, make_room, make_version

KITCHEN_MIC = "66666666-0000-0000-0000-00000000a101"


def count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_reset_removes_demo_rows_and_restores_seed(session):
    seed(session)
    # A rehearsal: new house + room + feed, a config change and clips on a seed feed, Maple deleted.
    elm = make_house(tenant_id=TENANT_A, name="Elm Ct")
    session.add(elm)
    session.flush()
    hall = make_room(elm.house_id, name="Hall")
    session.add(hall)
    session.flush()
    hall_mic = make_feed(elm, hall.room_id, name="Hall Mic")
    session.add(hall_mic)
    session.flush()
    session.add(make_version(hall_mic))
    mic = session.get(CameraFeed, KITCHEN_MIC)
    mic.config_version = 2
    mic.status = "active"
    mic.last_clip_at = datetime.now(UTC)
    session.add(make_version(mic, version=2, capture_interval_s=10))
    session.get(House, HOUSE_A1).deleted_at = datetime.now(UTC)
    session.flush()

    removed = reset(session)
    assert (removed["houses"], removed["rooms"], removed["feeds"]) == (1, 1, 1)
    assert removed["removed_feed_ids"] == [hall_mic.feed_id]
    session.expire_all()
    assert (count(session, House), count(session, Room), count(session, CameraFeed)) == (3, 15, 7)
    assert count(session, FeedConfigVersion) == 7
    mic = session.get(CameraFeed, KITCHEN_MIC)
    assert (mic.config_version, mic.status, mic.last_clip_at) == (1, "provisioned", None)
    assert session.get(House, HOUSE_A1).deleted_at is None
