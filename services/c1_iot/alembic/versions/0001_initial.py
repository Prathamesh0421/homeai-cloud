"""C1 initial schema: houses, rooms, camera_feeds, feed_config_versions (C1 plan §2.1).

Reader grants (contract 02 §5.1): ``c2_reader`` may read only ``houses`` and ``rooms``; ``c3_reader``
and ``c4_reader`` read every c1 table. ``infra/db/init.sql`` grants schema USAGE (and default
privileges for c3/c4 when ``c1_app`` creates the tables); this migration grants the tables
explicitly so the result is the same whoever runs it. Roles that do not exist (a database
without init.sql) are skipped.

Revision ID: 0001
Revises:
Create Date: 2026-11-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "c1"
UUID = postgresql.UUID(as_uuid=False)
TZ = sa.DateTime(timezone=True)

GRANTS = {
    "c2_reader": "GRANT SELECT ON c1.houses, c1.rooms TO c2_reader",
    "c3_reader": "GRANT SELECT ON ALL TABLES IN SCHEMA c1 TO c3_reader",
    "c4_reader": "GRANT SELECT ON ALL TABLES IN SCHEMA c1 TO c4_reader",
}


def _role_exists(role: str) -> bool:
    row = op.get_bind().execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
    return row.first() is not None


def upgrade() -> None:
    op.create_table(
        "houses",
        sa.Column("house_id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("address", sa.String(200)),
        sa.Column("timezone", sa.String(40), nullable=False),
        sa.Column("owner_user_id", UUID),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", TZ),
        schema=SCHEMA,
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_houses_tenant_name ON c1.houses (tenant_id, name) "
        "WHERE deleted_at IS NULL"
    )

    op.create_table(
        "rooms",
        sa.Column("room_id", UUID, primary_key=True),
        sa.Column(
            "house_id",
            UUID,
            sa.ForeignKey("c1.houses.house_id", name="fk_rooms_house"),
            nullable=False,
        ),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("room_type", sa.String(12), nullable=False),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("house_id", "name", name="uq_rooms_house_name"),
        sa.CheckConstraint(
            "room_type IN ('bedroom', 'kitchen', 'living', 'bathroom', 'entry', 'other')",
            name="ck_rooms_room_type",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "camera_feeds",
        sa.Column("feed_id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column(
            "house_id",
            UUID,
            sa.ForeignKey("c1.houses.house_id", name="fk_feeds_house"),
            nullable=False,
        ),
        sa.Column("room_id", UUID, sa.ForeignKey("c1.rooms.room_id", name="fk_feeds_room")),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("media_kind", sa.String(5), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default=sa.text("'provisioned'")),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "connectivity_status", sa.String(8), nullable=False, server_default=sa.text("'unknown'")
        ),
        sa.Column("config", postgresql.JSONB, nullable=False),
        sa.Column("config_version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("last_clip_at", TZ),
        sa.Column(
            "consecutive_failures", sa.SmallInteger, nullable=False, server_default=sa.text("0")
        ),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", TZ),
        sa.CheckConstraint("media_kind IN ('audio', 'video')", name="ck_feeds_media_kind"),
        sa.CheckConstraint(
            "status IN ('provisioned', 'active', 'inactive', 'error')", name="ck_feeds_status"
        ),
        sa.CheckConstraint(
            "connectivity_status IN ('online', 'offline', 'unknown')",
            name="ck_feeds_connectivity",
        ),
        schema=SCHEMA,
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_feeds_house_name ON c1.camera_feeds (house_id, name) "
        "WHERE archived_at IS NULL"
    )
    op.create_index(
        "ix_feeds_scope", "camera_feeds", ["tenant_id", "house_id", "status"], schema=SCHEMA
    )

    op.create_table(
        "feed_config_versions",
        sa.Column(
            "feed_id",
            UUID,
            sa.ForeignKey("c1.camera_feeds.feed_id", name="fk_versions_feed"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("capture_interval_s", sa.Integer, nullable=False),
        sa.Column("sensitivity", sa.String(6), nullable=False),
        sa.Column("network_label", sa.String(60)),
        sa.Column("created_by", UUID, nullable=False),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "capture_interval_s BETWEEN 5 AND 3600", name="ck_versions_capture_interval"
        ),
        sa.CheckConstraint(
            "sensitivity IN ('low', 'medium', 'high')", name="ck_versions_sensitivity"
        ),
        schema=SCHEMA,
    )

    for role, grant in GRANTS.items():
        if _role_exists(role):
            op.execute(grant)


def downgrade() -> None:
    for role in GRANTS:
        if _role_exists(role):
            op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA c1 FROM {role}")
    op.drop_table("feed_config_versions", schema=SCHEMA)
    op.drop_index("ix_feeds_scope", table_name="camera_feeds", schema=SCHEMA)
    op.execute("DROP INDEX IF EXISTS c1.ux_feeds_house_name")
    op.drop_table("camera_feeds", schema=SCHEMA)
    op.drop_table("rooms", schema=SCHEMA)
    op.execute("DROP INDEX IF EXISTS c1.ux_houses_tenant_name")
    op.drop_table("houses", schema=SCHEMA)
