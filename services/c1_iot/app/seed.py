"""C1 part of the demo seed: houses, rooms and camera feeds with the fixed IDs of
``scripts/seed_ids.py`` (docs/03_REPO_AND_INFRA.md §7).

Idempotent: rows that already exist are left as they are, so it can run on every deploy. Writes
as ``c1_app`` (``DATABASE_URL_C1``) after the migrations:

    make seed-c1                 # local (repo root on PYTHONPATH)
    make seed-c1-docker          # EC2, inside the c1-iot image with the repo mounted
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from homeai_common import db
from sqlalchemy.orm import Session

from app.models import CameraFeed, FeedConfigVersion, House, Room
from app.settings import get_settings

# scripts/seed_ids.py lives at the repo root: importable from a checkout (parents[3]) or, in the
# container, through PYTHONPATH=/workspace set by the Makefile.
_PARENTS = Path(__file__).resolve().parents
if len(_PARENTS) > 3 and str(_PARENTS[3]) not in sys.path:  # checkout: repo root
    sys.path.insert(0, str(_PARENTS[3]))

from scripts.seed_ids import FEEDS, HOUSES, ROOM_NAMES, ROOMS, TENANTS, USERS  # noqa: E402

logger = logging.getLogger(__name__)

ROOM_TYPES = {
    "Kitchen": "kitchen",
    "Bedroom 1": "bedroom",
    "Living": "living",
    "Bathroom": "bathroom",
    "Entryway": "entry",
}
SEED_CONFIG = {"capture_interval_s": 30, "sensitivity": "medium", "network_label": "home-wifi"}
OPS_USER = USERS["ops@homeai.test"][0]
OWNERS = {house: user_id for user_id, role, _, houses in USERS.values() for house in houses}


def seed(session: Session, now: datetime | None = None) -> dict[str, int]:
    """Create the missing seed rows; returns how many of each kind were created."""
    now = now or datetime.now(UTC)
    created = {"houses": 0, "rooms": 0, "feeds": 0}

    for alias, (house_id, tenant, name, timezone) in HOUSES.items():
        if session.get(House, house_id) is None:
            session.add(
                House(
                    house_id=house_id,
                    tenant_id=TENANTS[tenant],
                    name=name,
                    timezone=timezone,
                    owner_user_id=OWNERS.get(alias),
                    created_at=now,
                    updated_at=now,
                )
            )
            created["houses"] += 1
    session.flush()

    for (house, room_name), room_id in ROOMS.items():
        if session.get(Room, room_id) is None:
            session.add(
                Room(
                    room_id=room_id,
                    house_id=HOUSES[house][0],
                    name=room_name,
                    room_type=ROOM_TYPES.get(room_name, "other"),
                    created_at=now,
                )
            )
            created["rooms"] += 1
    session.flush()

    for alias, (feed_id, house, room_name, name, media_kind, enabled) in FEEDS.items():
        if session.get(CameraFeed, feed_id) is not None:
            continue
        house_id, tenant, _, _ = HOUSES[house]
        feed = CameraFeed(
            feed_id=feed_id,
            tenant_id=TENANTS[tenant],
            house_id=house_id,
            room_id=ROOMS[(house, room_name)] if room_name else None,
            name=name,
            media_kind=media_kind,
            status="provisioned",
            is_enabled=enabled,
            connectivity_status="unknown",
            config=dict(SEED_CONFIG),
            config_version=1,
            created_at=now,
            updated_at=now,
        )
        if alias == "maple_garage_cam":
            # Enabled but silent for two days: shows as inactive/offline (docs/03 §7).
            feed.last_clip_at = now - timedelta(days=2)
            feed.status = "inactive"
            feed.connectivity_status = "offline"
        session.add(feed)
        session.flush()
        session.add(
            FeedConfigVersion(
                feed_id=feed_id,
                version=1,
                capture_interval_s=SEED_CONFIG["capture_interval_s"],
                sensitivity=SEED_CONFIG["sensitivity"],
                network_label=SEED_CONFIG["network_label"],
                created_by=OPS_USER,
                created_at=now,
            )
        )
        created["feeds"] += 1
    session.flush()
    return created


def main() -> int:
    settings = get_settings()
    db.configure_db(settings.database_url)
    try:
        with db.session_scope() as session:
            created = seed(session)
    finally:
        db.dispose_db()
    print(
        f"c1 seed: {created['houses']} house(s), {created['rooms']} room(s), "
        f"{created['feeds']} feed(s) created ({len(ROOM_NAMES)} rooms per house)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
