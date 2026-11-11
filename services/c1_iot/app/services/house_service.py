"""Houses and rooms business rules (C1 plan §3.1).

- Duplicate house name in a tenant, or room name in a house → 422 on field ``name``.
- ``DELETE /houses/{id}`` → 409 ``house_not_empty`` while any feed is enabled; else soft delete.
- ``DELETE /rooms/{id}`` → 409 ``room_in_use`` while a non-archived feed is in the room.
- Rows outside the caller's scope are 404.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from homeai_common.auth import Principal
from sqlalchemy.orm import Session

from app.models import House, Room
from app.repositories.house_repo import HouseRepository, RoomRepository
from app.repositories.scope import Scope
from app.schemas.house import HouseCreate, HouseOut, HouseUpdate, RoomCreate, RoomOut, RoomUpdate
from app.services.errors import conflict, invalid, not_found


def utc_now() -> datetime:
    return datetime.now(UTC)


def house_out(house: House, counts: tuple[int, int] = (0, 0)) -> HouseOut:
    return HouseOut(
        house_id=house.house_id,
        tenant_id=house.tenant_id,
        name=house.name,
        address=house.address,
        timezone=house.timezone,
        owner_user_id=house.owner_user_id,
        room_count=counts[0],
        feed_count=counts[1],
        created_at=house.created_at,
        updated_at=house.updated_at,
    )


def room_out(room: Room) -> RoomOut:
    return RoomOut(
        room_id=room.room_id,
        house_id=room.house_id,
        name=room.name,
        room_type=room.room_type,
        created_at=room.created_at,
    )


class HouseService:
    def __init__(
        self,
        session: Session,
        *,
        demo_mode: bool = False,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.session = session
        self.houses = HouseRepository(session)
        self.rooms = RoomRepository(session)
        self.demo_mode = demo_mode
        self.clock = clock

    # --- houses ---------------------------------------------------------------------------

    def _house(self, house_id: str, scope: Scope) -> House:
        house = self.houses.get(house_id, scope)
        if house is None:
            raise not_found("house")
        return house

    def list_houses(
        self, scope: Scope, *, q: str | None, offset: int, limit: int
    ) -> tuple[list[HouseOut], int]:
        rows, total = self.houses.list(scope, q=q, offset=offset, limit=limit)
        counts = self.houses.counts(h.house_id for h in rows)
        return [house_out(h, counts.get(h.house_id, (0, 0))) for h in rows], total

    def get_house(self, house_id: str, scope: Scope) -> HouseOut:
        house = self._house(house_id, scope)
        return house_out(house, self.houses.counts([house_id])[house_id])

    def create_house(self, principal: Principal, body: HouseCreate) -> HouseOut:
        if principal.is_cloud_staff():
            if not body.tenant_id:
                raise invalid("tenant_id", "required for cloud staff")
            tenant_id = body.tenant_id
        else:
            tenant_id = principal.tenant_id or ""
        if body.house_id is not None:
            if not self.demo_mode:
                raise invalid("house_id", "only accepted when DEMO_MODE is on")
            if self.houses.id_exists(body.house_id):
                raise invalid("house_id", "a house with this id already exists")
        if self.houses.name_taken(tenant_id, body.name):
            raise invalid("name", "a house with this name already exists in the tenant")
        now = self.clock()
        house = House(
            house_id=body.house_id or str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=body.name,
            address=body.address,
            timezone=body.timezone,
            owner_user_id=body.owner_user_id,
            created_at=now,
            updated_at=now,
        )
        self.session.add(house)
        self.session.commit()
        return house_out(house)

    def update_house(self, house_id: str, scope: Scope, body: HouseUpdate) -> HouseOut:
        house = self._house(house_id, scope)
        changes = body.model_dump(exclude_unset=True)
        for field in ("name", "timezone"):
            if field in changes and changes[field] is None:
                raise invalid(field, "may not be null")
        if "name" in changes and self.houses.name_taken(
            house.tenant_id, changes["name"], exclude_id=house_id
        ):
            raise invalid("name", "a house with this name already exists in the tenant")
        for field, value in changes.items():
            setattr(house, field, value)
        house.updated_at = self.clock()
        self.session.commit()
        return house_out(house, self.houses.counts([house_id])[house_id])

    def delete_house(self, house_id: str, scope: Scope) -> None:
        house = self._house(house_id, scope)
        if self.houses.has_enabled_feeds(house_id):
            raise conflict("house_not_empty", "disable or archive the house's feeds first")
        house.deleted_at = self.clock()
        house.updated_at = house.deleted_at
        self.session.commit()

    # --- rooms ----------------------------------------------------------------------------

    def _room(self, room_id: str, scope: Scope) -> Room:
        room = self.rooms.get(room_id, scope)
        if room is None:
            raise not_found("room")
        return room

    def list_rooms(self, house_id: str, scope: Scope) -> list[RoomOut]:
        self._house(house_id, scope)
        return [room_out(r) for r in self.rooms.list_for_house(house_id)]

    def create_room(self, house_id: str, scope: Scope, body: RoomCreate) -> RoomOut:
        self._house(house_id, scope)
        if self.rooms.name_taken(house_id, body.name):
            raise invalid("name", "a room with this name already exists in the house")
        room = Room(
            room_id=str(uuid.uuid4()),
            house_id=house_id,
            name=body.name,
            room_type=body.room_type,
            created_at=self.clock(),
        )
        self.session.add(room)
        self.session.commit()
        return room_out(room)

    def update_room(self, room_id: str, scope: Scope, body: RoomUpdate) -> RoomOut:
        room = self._room(room_id, scope)
        changes = body.model_dump(exclude_unset=True)
        for field in ("name", "room_type"):
            if field in changes and changes[field] is None:
                raise invalid(field, "may not be null")
        if "name" in changes and self.rooms.name_taken(
            room.house_id, changes["name"], exclude_id=room_id
        ):
            raise invalid("name", "a room with this name already exists in the house")
        for field, value in changes.items():
            setattr(room, field, value)
        self.session.commit()
        return room_out(room)

    def delete_room(self, room_id: str, scope: Scope) -> None:
        room = self._room(room_id, scope)
        if self.rooms.in_use(room_id):
            raise conflict("room_in_use", "move or archive the feeds in this room first")
        self.rooms.detach_archived_feeds(room_id)
        self.session.delete(room)
        self.session.commit()
