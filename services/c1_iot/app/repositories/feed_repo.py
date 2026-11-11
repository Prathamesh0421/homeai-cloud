"""Camera feeds and their config versions (schema ``c1``). Every read takes a ``Scope``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, case, func, select, update
from sqlalchemy.orm import Session

from app.models import CameraFeed, FeedConfigVersion, House, Room
from app.repositories.scope import Scope


@dataclass(frozen=True)
class FeedFilters:
    house_id: str | None = None
    room_id: str | None = None
    media_kind: str | None = None
    status: str | None = None
    connectivity_status: str | None = None
    is_enabled: bool | None = None
    include_archived: bool = False


@dataclass(frozen=True)
class FeedRow:
    """A feed with the names of its house and room (for ``FeedOut``)."""

    feed: CameraFeed
    house_name: str
    room_name: str | None


class FeedRepository:
    def __init__(self, session: Session):
        self.session = session

    def _named(self) -> Select:
        return (
            select(CameraFeed, House.name, Room.name)
            .join(House, House.house_id == CameraFeed.house_id)
            .outerjoin(Room, Room.room_id == CameraFeed.room_id)
            .where(House.deleted_at.is_(None))
        )

    def get_row(self, feed_id: str, scope: Scope) -> FeedRow | None:
        stmt = scope.apply(self._named().where(CameraFeed.feed_id == feed_id), CameraFeed)
        row = self.session.execute(stmt).first()
        return FeedRow(*row) if row else None

    def get(self, feed_id: str, scope: Scope, *, for_update: bool = False) -> CameraFeed | None:
        """The feed (archived ones too) if visible to ``scope``; optionally row-locked."""
        stmt = (
            select(CameraFeed)
            .join(House, House.house_id == CameraFeed.house_id)
            .where(CameraFeed.feed_id == feed_id, House.deleted_at.is_(None))
        )
        stmt = scope.apply(stmt, CameraFeed)
        if for_update:
            stmt = stmt.with_for_update(of=CameraFeed)
        return self.session.scalars(stmt).first()

    def list(
        self, scope: Scope, filters: FeedFilters, *, offset: int, limit: int
    ) -> tuple[list[FeedRow], int]:
        stmt = scope.apply(self._named(), CameraFeed)
        f = filters
        if not f.include_archived:
            stmt = stmt.where(CameraFeed.archived_at.is_(None))
        for column, value in (
            (CameraFeed.house_id, f.house_id),
            (CameraFeed.room_id, f.room_id),
            (CameraFeed.media_kind, f.media_kind),
            (CameraFeed.status, f.status),
            (CameraFeed.connectivity_status, f.connectivity_status),
            (CameraFeed.is_enabled, f.is_enabled),
        ):
            if value is not None:
                stmt = stmt.where(column == value)
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        stmt = stmt.order_by(CameraFeed.created_at.desc(), CameraFeed.name)
        rows = self.session.execute(stmt.offset(offset).limit(limit)).all()
        return [FeedRow(*r) for r in rows], total

    def by_ids(self, feed_ids: list[str]) -> dict[str, FeedRow]:
        """Feeds with names for clip lists (no scope: the clips were already scoped)."""
        ids = sorted(set(feed_ids))
        if not ids:
            return {}
        stmt = (
            select(CameraFeed, House.name, Room.name)
            .join(House, House.house_id == CameraFeed.house_id)
            .outerjoin(Room, Room.room_id == CameraFeed.room_id)
            .where(CameraFeed.feed_id.in_(ids))
        )
        return {r[0].feed_id: FeedRow(*r) for r in self.session.execute(stmt).all()}

    def name_taken(self, house_id: str, name: str, *, exclude_id: str | None = None) -> bool:
        stmt = select(CameraFeed.feed_id).where(
            CameraFeed.house_id == house_id,
            func.lower(CameraFeed.name) == name.lower(),
            CameraFeed.archived_at.is_(None),
        )
        if exclude_id:
            stmt = stmt.where(CameraFeed.feed_id != exclude_id)
        return self.session.scalars(stmt).first() is not None

    # --- config versions ------------------------------------------------------------------

    def versions(self, feed_id: str) -> list[FeedConfigVersion]:
        stmt = (
            select(FeedConfigVersion)
            .where(FeedConfigVersion.feed_id == feed_id)
            .order_by(FeedConfigVersion.version.desc())
        )
        return list(self.session.scalars(stmt).all())

    def version(self, feed_id: str, version: int) -> FeedConfigVersion | None:
        return self.session.get(FeedConfigVersion, (feed_id, version))

    # --- statistics -----------------------------------------------------------------------

    def stats(self, scope: Scope, house_id: str | None) -> tuple[int, dict[str, int], int]:
        """``(houses, {status: count}, online)`` over non-archived feeds in scope."""
        houses = scope.apply(select(func.count()).select_from(House), House).where(
            House.deleted_at.is_(None)
        )
        feeds = scope.apply(
            select(CameraFeed.status, CameraFeed.connectivity_status, func.count())
            .join(House, House.house_id == CameraFeed.house_id)
            .where(CameraFeed.archived_at.is_(None), House.deleted_at.is_(None)),
            CameraFeed,
        )
        if house_id:
            houses = houses.where(House.house_id == house_id)
            feeds = feeds.where(CameraFeed.house_id == house_id)
        feeds = feeds.group_by(CameraFeed.status, CameraFeed.connectivity_status)
        by_status: dict[str, int] = {}
        online = 0
        for status, connectivity, count in self.session.execute(feeds).all():
            by_status[status] = by_status.get(status, 0) + count
            if connectivity == "online":
                online += count
        return self.session.scalar(houses) or 0, by_status, online

    # --- ingest bookkeeping (C1 plan §4.1 steps 7-9) ---------------------------------------

    def record_failure(self, feed_id: str, now: datetime, *, error_after: int = 3) -> None:
        """``consecutive_failures += 1``; the feed goes to ``error`` when it reaches the limit."""
        failures = CameraFeed.consecutive_failures + 1
        self.session.execute(
            update(CameraFeed)
            .where(CameraFeed.feed_id == feed_id)
            .values(
                consecutive_failures=failures,
                status=case((failures >= error_after, "error"), else_=CameraFeed.status),
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        self.session.expire_all()

    def touch_last_clip(self, feed_id: str, captured_at: datetime, now: datetime) -> None:
        """A clip arrived: online, active (unless in error), failures reset."""
        feed = self.session.get(CameraFeed, feed_id)
        if feed is None:  # pragma: no cover - checked by the caller
            return
        if feed.last_clip_at is None or captured_at > feed.last_clip_at:
            feed.last_clip_at = captured_at
        feed.connectivity_status = "online"
        if feed.status in ("provisioned", "inactive"):
            feed.status = "active"
        feed.consecutive_failures = 0
        feed.updated_at = now
