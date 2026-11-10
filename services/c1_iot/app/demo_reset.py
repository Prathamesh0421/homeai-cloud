"""Demo reset for C1: put houses, rooms and feeds back to the seed (rehearse, then demo).

Removes every house, room and feed that is not in ``scripts/seed_ids.py`` (with their config
versions and the ``media_events`` of the removed feeds), recreates the seed feeds in their seed
state (config v1, no clips yet, seed status), brings back soft-deleted seed houses and re-runs
the seed for anything missing. Clips of seed feeds are kept (C3 detections and C2 alerts point at
them); S3 objects are left alone (the bucket lifecycle expires them). C2's alerts have their own
reset (``make demo-c2-reset``).

    make demo-c1-reset ARGS=--yes      # runs ``python -m app.demo_reset --yes`` in the container
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from homeai_common import db
from homeai_common.mongo import get_mongo_db
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.mongo_indexes import MEDIA_EVENTS
from app.models import CameraFeed, FeedConfigVersion, House, Room
from app.seed import FEEDS, HOUSES, ROOMS, seed
from app.settings import get_settings

SEED_HOUSES = {h[0] for h in HOUSES.values()}
SEED_ROOMS = set(ROOMS.values())
SEED_FEEDS = {f[0] for f in FEEDS.values()}


def reset(session: Session, now: datetime | None = None) -> dict[str, object]:
    """Back to the seed. Returns the removed counts and the removed feed ids (for their clips)."""
    removed_feeds = list(
        session.scalars(select(CameraFeed.feed_id).where(CameraFeed.feed_id.not_in(SEED_FEEDS)))
    )
    # Every feed goes (seed ones are recreated below in their seed state); versions first (FK).
    session.execute(delete(FeedConfigVersion))
    session.execute(delete(CameraFeed))
    rooms = session.execute(delete(Room).where(Room.room_id.not_in(SEED_ROOMS))).rowcount
    houses = session.execute(delete(House).where(House.house_id.not_in(SEED_HOUSES))).rowcount
    for house in session.scalars(select(House).where(House.deleted_at.is_not(None))):
        house.deleted_at = None  # a seed house deleted in a rehearsal comes back
    session.flush()
    seed(session, now or datetime.now(UTC))
    return {
        "houses": houses,
        "rooms": rooms,
        "feeds": len(removed_feeds),
        "removed_feed_ids": removed_feeds,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset C1 demo data to the seed.")
    parser.add_argument("--yes", action="store_true", help="really delete the demo rows")
    args = parser.parse_args(argv)
    if not args.yes:
        print("c1 demo reset: dry run; pass --yes to delete demo houses, rooms and feeds")
        return 1
    settings = get_settings()
    db.configure_db(settings.database_url)
    try:
        with db.session_scope() as session:
            removed = reset(session)
    finally:
        db.dispose_db()
    clips = 0
    if settings.mongo_url and removed["removed_feed_ids"]:
        events = get_mongo_db(settings.mongo_url)[MEDIA_EVENTS]
        clips = events.delete_many({"feed_id": {"$in": removed["removed_feed_ids"]}}).deleted_count
    print(
        f"c1 demo reset: removed {removed['houses']} house(s), {removed['rooms']} room(s), "
        f"{removed['feeds']} feed(s) and their {clips} clip record(s); seed feeds back to v1"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
