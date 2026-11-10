"""ORM classes for schema ``c1`` (docs/components/C1_IOT_DEVICE_MANAGER.md §2.1).

Must stay in step with ``alembic/versions`` — CI runs ``alembic check``. The two partial unique
indexes (``ux_houses_tenant_name``, ``ux_feeds_house_name``) live only in migration 0001.

IDs are UUID strings (``as_uuid=False``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

UUIDStr = UUID(as_uuid=False)
TZ = DateTime(timezone=True)

ROOM_TYPES = ("bedroom", "kitchen", "living", "bathroom", "entry", "other")
MEDIA_KINDS = ("audio", "video")
FEED_STATUSES = ("provisioned", "active", "inactive", "error")
CONNECTIVITY = ("online", "offline", "unknown")
SENSITIVITIES = ("low", "medium", "high")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class House(Base):
    __tablename__ = "houses"

    house_id: Mapped[str] = mapped_column(UUIDStr, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(UUIDStr, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    address: Mapped[str | None] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(40), nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(UUIDStr)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(TZ)


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (
        UniqueConstraint("house_id", "name", name="uq_rooms_house_name"),
        CheckConstraint(_in("room_type", ROOM_TYPES), name="ck_rooms_room_type"),
    )

    room_id: Mapped[str] = mapped_column(UUIDStr, primary_key=True)
    house_id: Mapped[str] = mapped_column(
        UUIDStr, ForeignKey("houses.house_id", name="fk_rooms_house"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    room_type: Mapped[str] = mapped_column(String(12), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


class CameraFeed(Base):
    __tablename__ = "camera_feeds"
    __table_args__ = (
        CheckConstraint(_in("media_kind", MEDIA_KINDS), name="ck_feeds_media_kind"),
        CheckConstraint(_in("status", FEED_STATUSES), name="ck_feeds_status"),
        CheckConstraint(_in("connectivity_status", CONNECTIVITY), name="ck_feeds_connectivity"),
        Index("ix_feeds_scope", "tenant_id", "house_id", "status"),
    )

    feed_id: Mapped[str] = mapped_column(UUIDStr, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(UUIDStr, nullable=False)
    house_id: Mapped[str] = mapped_column(
        UUIDStr, ForeignKey("houses.house_id", name="fk_feeds_house"), nullable=False
    )
    room_id: Mapped[str | None] = mapped_column(
        UUIDStr, ForeignKey("rooms.room_id", name="fk_feeds_room")
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    media_kind: Mapped[str] = mapped_column(String(5), nullable=False)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default=text("'provisioned'")
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    connectivity_status: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'unknown'")
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    last_clip_at: Mapped[datetime | None] = mapped_column(TZ)
    consecutive_failures: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(TZ)


class FeedConfigVersion(Base):
    __tablename__ = "feed_config_versions"
    __table_args__ = (
        CheckConstraint(
            "capture_interval_s BETWEEN 5 AND 3600", name="ck_versions_capture_interval"
        ),
        CheckConstraint(_in("sensitivity", SENSITIVITIES), name="ck_versions_sensitivity"),
    )

    feed_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("camera_feeds.feed_id", name="fk_versions_feed"),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    capture_interval_s: Mapped[int] = mapped_column(Integer, nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(6), nullable=False)
    network_label: Mapped[str | None] = mapped_column(String(60))
    created_by: Mapped[str] = mapped_column(UUIDStr, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
