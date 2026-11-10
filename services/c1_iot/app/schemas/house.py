"""Houses and rooms API models (C1 plan §3.1)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, StringConstraints

from app.schemas.common import RoomType, Timezone, UtcDatetime, UuidStr

HouseName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Address = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
RoomName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class HouseCreate(BaseModel):
    name: HouseName
    address: Address | None = None
    timezone: Timezone
    owner_user_id: UuidStr | None = None
    # Required for cloud_staff (they have no tenant of their own); ignored for iot_staff.
    tenant_id: UuidStr | None = None
    # Fixed seed IDs; accepted only when DEMO_MODE=1 [D3 addition].
    house_id: UuidStr | None = None


class HouseUpdate(BaseModel):
    """Only the fields sent are changed."""

    name: HouseName | None = None
    address: Address | None = None
    timezone: Timezone | None = None
    owner_user_id: UuidStr | None = None


class HouseOut(BaseModel):
    house_id: str
    tenant_id: str
    name: str
    address: str | None
    timezone: str
    owner_user_id: str | None
    room_count: int
    feed_count: int
    created_at: UtcDatetime
    updated_at: UtcDatetime


class RoomCreate(BaseModel):
    name: RoomName
    room_type: RoomType


class RoomUpdate(BaseModel):
    name: RoomName | None = None
    room_type: RoomType | None = None


class RoomOut(BaseModel):
    room_id: str
    house_id: str
    name: str
    room_type: RoomType
    created_at: UtcDatetime
