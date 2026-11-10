"""Houses and rooms (schema ``c1``). Every read takes a ``Scope``; deleted houses are invisible."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import CameraFeed, House, Room
from app.repositories.scope import Scope


class HouseRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, house_id: str, scope: Scope) -> House | None:
        stmt = select(House).where(House.house_id == house_id, House.deleted_at.is_(None))
        return self.session.scalars(scope.apply(stmt, House)).first()

    def list(
        self, scope: Scope, *, q: str | None, offset: int, limit: int
    ) -> tuple[list[House], int]:
        stmt = scope.apply(select(House).where(House.deleted_at.is_(None)), House)
        if q:
            stmt = stmt.where(House.name.ilike(f"%{q}%"))
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.scalars(stmt.order_by(House.name).offset(offset).limit(limit)).all()
        return list(rows), total

    def id_exists(self, house_id: str) -> bool:
        """Any house with this id, deleted or not (fixed seed ids must stay unique)."""
        return self.session.get(House, house_id) is not None

    def name_taken(self, tenant_id: str, name: str, *, exclude_id: str | None = None) -> bool:
        stmt = select(House.house_id).where(
            House.tenant_id == tenant_id,
            func.lower(House.name) == name.lower(),
            House.deleted_at.is_(None),
        )
        if exclude_id:
            stmt = stmt.where(House.house_id != exclude_id)
        return self.session.scalars(stmt).first() is not None

    def counts(self, house_ids: Iterable[str]) -> dict[str, tuple[int, int]]:
        """``{house_id: (room_count, feed_count)}``; archived feeds are not counted."""
        ids = list(house_ids)
        if not ids:
            return {}
        rooms = dict(
            self.session.execute(
                select(Room.house_id, func.count())
                .where(Room.house_id.in_(ids))
                .group_by(Room.house_id)
            ).all()
        )
        feeds = dict(
            self.session.execute(
                select(CameraFeed.house_id, func.count())
                .where(CameraFeed.house_id.in_(ids), CameraFeed.archived_at.is_(None))
                .group_by(CameraFeed.house_id)
            ).all()
        )
        return {h: (rooms.get(h, 0), feeds.get(h, 0)) for h in ids}

    def has_enabled_feeds(self, house_id: str) -> bool:
        stmt = select(CameraFeed.feed_id).where(
            CameraFeed.house_id == house_id,
            CameraFeed.is_enabled.is_(True),
            CameraFeed.archived_at.is_(None),
        )
        return self.session.scalars(stmt).first() is not None


class RoomRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_for_house(self, house_id: str) -> list[Room]:
        stmt = select(Room).where(Room.house_id == house_id).order_by(Room.name)
        return list(self.session.scalars(stmt).all())

    def get(self, room_id: str, scope: Scope) -> Room | None:
        """The room, if its house is visible to ``scope`` and not deleted."""
        stmt = (
            select(Room)
            .join(House, House.house_id == Room.house_id)
            .where(Room.room_id == room_id, House.deleted_at.is_(None))
        )
        return self.session.scalars(scope.apply(stmt, House)).first()

    def by_ids(self, room_ids: Iterable[str]) -> dict[str, Room]:
        ids = sorted({r for r in room_ids if r})
        if not ids:
            return {}
        return {
            r.room_id: r for r in self.session.scalars(select(Room).where(Room.room_id.in_(ids)))
        }

    def name_taken(self, house_id: str, name: str, *, exclude_id: str | None = None) -> bool:
        stmt = select(Room.room_id).where(
            Room.house_id == house_id, func.lower(Room.name) == name.lower()
        )
        if exclude_id:
            stmt = stmt.where(Room.room_id != exclude_id)
        return self.session.scalars(stmt).first() is not None

    def in_use(self, room_id: str) -> bool:
        """True if a non-archived feed is placed in this room."""
        stmt = select(CameraFeed.feed_id).where(
            CameraFeed.room_id == room_id, CameraFeed.archived_at.is_(None)
        )
        return self.session.scalars(stmt).first() is not None

    def detach_archived_feeds(self, room_id: str) -> None:
        """Archived feeds keep no room, so the room row can be deleted (foreign key)."""
        self.session.execute(
            update(CameraFeed)
            .where(CameraFeed.room_id == room_id, CameraFeed.archived_at.is_not(None))
            .values(room_id=None)
        )
