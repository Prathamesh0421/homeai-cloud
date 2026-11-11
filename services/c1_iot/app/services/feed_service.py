"""Camera feed business rules (C1 plan §3.2) and config versioning (§3.2, C1-05).

- A new feed is ``provisioned``, disabled, ``config_version=1`` with its version row.
- The room must belong to the feed's house (422 on ``room_id``).
- Enabling needs a room (409 ``room_required``), and so does keeping an enabled feed when its
  room is cleared. Enabling a feed in ``error`` resets it to ``provisioned`` with 0 failures.
- ``DELETE`` archives (disables, sets ``archived_at``). Archived feeds can be read but not changed.
- ``PUT /config`` writes version n+1; restoring version v copies it into n+1.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from homeai_common.auth import Principal
from sqlalchemy.orm import Session

from app.models import CameraFeed, FeedConfigVersion
from app.repositories.feed_repo import FeedFilters, FeedRepository, FeedRow
from app.repositories.house_repo import HouseRepository, RoomRepository
from app.repositories.scope import Scope
from app.schemas.feed import (
    ConfigResult,
    ConfigVersionOut,
    FeedConfig,
    FeedCreate,
    FeedDetailOut,
    FeedOut,
    FeedStats,
    FeedUpdate,
    RecentClip,
)
from app.services.errors import conflict, invalid, not_found

FEED_STATUSES = ("provisioned", "active", "inactive", "error")


def utc_now() -> datetime:
    return datetime.now(UTC)


def feed_out(row: FeedRow) -> FeedOut:
    f = row.feed
    return FeedOut(
        feed_id=f.feed_id,
        tenant_id=f.tenant_id,
        house_id=f.house_id,
        house_name=row.house_name,
        room_id=f.room_id,
        room_name=row.room_name,
        name=f.name,
        media_kind=f.media_kind,
        status=f.status,
        is_enabled=f.is_enabled,
        connectivity_status=f.connectivity_status,
        config=FeedConfig(**f.config),
        config_version=f.config_version,
        last_clip_at=f.last_clip_at,
        created_at=f.created_at,
        archived_at=f.archived_at,
    )


def version_out(v: FeedConfigVersion) -> ConfigVersionOut:
    return ConfigVersionOut(
        version=v.version,
        capture_interval_s=v.capture_interval_s,
        sensitivity=v.sensitivity,
        network_label=v.network_label,
        created_by=v.created_by,
        created_at=v.created_at,
    )


class FeedService:
    def __init__(self, session: Session, *, clock: Callable[[], datetime] = utc_now):
        self.session = session
        self.feeds = FeedRepository(session)
        self.houses = HouseRepository(session)
        self.rooms = RoomRepository(session)
        self.clock = clock

    # --- reads ----------------------------------------------------------------------------

    def _row(self, feed_id: str, scope: Scope) -> FeedRow:
        row = self.feeds.get_row(feed_id, scope)
        if row is None:
            raise not_found("feed")
        return row

    def list_feeds(
        self, scope: Scope, filters: FeedFilters, *, offset: int, limit: int
    ) -> tuple[list[FeedOut], int]:
        rows, total = self.feeds.list(scope, filters, offset=offset, limit=limit)
        return [feed_out(r) for r in rows], total

    def get_feed(
        self,
        feed_id: str,
        scope: Scope,
        recent_clips: Callable[[str], list[RecentClip]] | None = None,
    ) -> FeedDetailOut:
        row = self._row(feed_id, scope)
        clips = recent_clips(feed_id) if recent_clips else []
        return FeedDetailOut(**feed_out(row).model_dump(), recent_clips=clips)

    def stats(self, scope: Scope, house_id: str | None) -> FeedStats:
        houses, by_status, online = self.feeds.stats(scope, house_id)
        return FeedStats(
            houses=houses,
            total=sum(by_status.values()),
            by_status={s: by_status.get(s, 0) for s in FEED_STATUSES},
            online=online,
        )

    # --- writes ---------------------------------------------------------------------------

    def _live(self, feed_id: str, scope: Scope) -> CameraFeed:
        """A feed that may be changed: visible, not archived, row-locked."""
        feed = self.feeds.get(feed_id, scope, for_update=True)
        if feed is None or feed.archived_at is not None:
            raise not_found("feed")
        return feed

    def _check_room(self, house_id: str, room_id: str, scope: Scope) -> None:
        room = self.rooms.get(room_id, scope)
        if room is None or room.house_id != house_id:
            raise invalid("room_id", "room does not belong to the feed's house")

    def create_feed(self, principal: Principal, body: FeedCreate) -> FeedOut:
        scope = Scope.for_principal(principal)
        house = self.houses.get(body.house_id, scope)
        if house is None:
            raise invalid("house_id", "unknown house")
        if body.room_id:
            self._check_room(house.house_id, body.room_id, scope)
        if self.feeds.name_taken(house.house_id, body.name):
            raise invalid("name", "a feed with this name already exists in the house")
        now = self.clock()
        config = body.config.model_dump()
        feed = CameraFeed(
            feed_id=str(uuid.uuid4()),
            tenant_id=house.tenant_id,
            house_id=house.house_id,
            room_id=body.room_id,
            name=body.name,
            media_kind=body.media_kind,
            status="provisioned",
            is_enabled=False,
            connectivity_status="unknown",
            config=config,
            config_version=1,
            consecutive_failures=0,
            created_at=now,
            updated_at=now,
        )
        self.session.add(feed)
        self.session.flush()
        self.session.add(
            FeedConfigVersion(
                feed_id=feed.feed_id, version=1, created_by=principal.sub, created_at=now, **config
            )
        )
        self.session.commit()
        return feed_out(self._row(feed.feed_id, scope))

    def update_feed(self, feed_id: str, scope: Scope, body: FeedUpdate) -> FeedOut:
        feed = self._live(feed_id, scope)
        changes = body.model_dump(exclude_unset=True)
        if "name" in changes:
            if changes["name"] is None:
                raise invalid("name", "may not be null")
            if self.feeds.name_taken(feed.house_id, changes["name"], exclude_id=feed_id):
                raise invalid("name", "a feed with this name already exists in the house")
            feed.name = changes["name"]
        if "room_id" in changes:
            room_id = changes["room_id"]
            if room_id is None and feed.is_enabled:
                raise conflict(
                    "room_required", "an enabled feed must stay in a room; disable it first"
                )
            if room_id is not None:
                self._check_room(feed.house_id, room_id, scope)
            feed.room_id = room_id
        feed.updated_at = self.clock()
        self.session.commit()
        return feed_out(self._row(feed_id, scope))

    def set_enabled(self, feed_id: str, scope: Scope, enabled: bool) -> FeedOut:
        feed = self._live(feed_id, scope)
        if enabled:
            if feed.room_id is None:
                raise conflict("room_required", "assign the feed to a room before enabling it")
            if feed.status == "error":
                feed.status = "provisioned"
                feed.consecutive_failures = 0
        feed.is_enabled = enabled
        feed.updated_at = self.clock()
        self.session.commit()
        return feed_out(self._row(feed_id, scope))

    def archive(self, feed_id: str, scope: Scope) -> None:
        feed = self.feeds.get(feed_id, scope, for_update=True)
        if feed is None:
            raise not_found("feed")
        if feed.archived_at is None:  # archiving twice is a no-op
            now = self.clock()
            feed.is_enabled = False
            feed.archived_at = now
            feed.updated_at = now
        self.session.commit()

    # --- config versions (C1-05) ----------------------------------------------------------

    def _new_version(self, feed: CameraFeed, config: dict, actor: str) -> ConfigResult:
        now = self.clock()
        version = feed.config_version + 1
        self.session.add(
            FeedConfigVersion(
                feed_id=feed.feed_id, version=version, created_by=actor, created_at=now, **config
            )
        )
        feed.config = config
        feed.config_version = version
        feed.updated_at = now
        self.session.commit()
        return ConfigResult(config_version=version, config=FeedConfig(**config))

    def put_config(self, feed_id: str, scope: Scope, body: FeedConfig, actor: str) -> ConfigResult:
        return self._new_version(self._live(feed_id, scope), body.model_dump(), actor)

    def list_versions(self, feed_id: str, scope: Scope) -> list[ConfigVersionOut]:
        self._row(feed_id, scope)
        return [version_out(v) for v in self.feeds.versions(feed_id)]

    def restore_version(self, feed_id: str, scope: Scope, version: int, actor: str) -> ConfigResult:
        feed = self._live(feed_id, scope)
        old = self.feeds.version(feed_id, version)
        if old is None:
            raise not_found("config version")
        config = {
            "capture_interval_s": old.capture_interval_s,
            "sensitivity": old.sensitivity,
            "network_label": old.network_label,
        }
        return self._new_version(feed, config, actor)
