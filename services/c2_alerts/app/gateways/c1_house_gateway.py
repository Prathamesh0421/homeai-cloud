"""C1 houses (tenant, name, timezone) and rooms (read-only, contracts §4.5)."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.gateways.readonly_tables import houses as h
from app.gateways.readonly_tables import rooms as r
from app.gateways.sql_errors import read_or_unavailable
from app.gateways.types import House, Room

SOURCE = "c1"


class C1HouseGateway:
    """Implements ``HouseReader`` over the ``c2_reader`` session. Deleted houses are invisible."""

    def __init__(self, session: Session):
        self.session = session

    def _houses(self, house_ids: list[str]) -> dict[str, House]:
        if not house_ids:
            return {}
        stmt = select(h.c.house_id, h.c.tenant_id, h.c.name, h.c.timezone).where(
            h.c.house_id.in_(house_ids), h.c.deleted_at.is_(None)
        )
        rows = read_or_unavailable(self.session, SOURCE, lambda: self.session.execute(stmt).all())
        return {row.house_id: House(*row) for row in rows}

    def _rooms(self, room_ids: list[str]) -> dict[str, Room]:
        if not room_ids:
            return {}
        stmt = select(r.c.room_id, r.c.house_id, r.c.name).where(r.c.room_id.in_(room_ids))
        rows = read_or_unavailable(self.session, SOURCE, lambda: self.session.execute(stmt).all())
        return {row.room_id: Room(*row) for row in rows}

    def house(self, house_id: str) -> House | None:
        return self._houses([house_id]).get(house_id)

    def room(self, room_id: str) -> Room | None:
        return self._rooms([room_id]).get(room_id)

    def houses(self, house_ids: Iterable[str]) -> dict[str, House]:
        """Batch lookup for list pages (house names) without N+1 queries."""
        return self._houses(sorted(set(house_ids)))

    def rooms(self, room_ids: Iterable[str]) -> dict[str, Room]:
        return self._rooms(sorted({rid for rid in room_ids if rid}))
