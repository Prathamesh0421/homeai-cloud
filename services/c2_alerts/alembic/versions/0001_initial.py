"""C2 initial schema: alert_types, alert_rules, alerts, alert_status_history, notifications.

Revision ID: 0001
Revises:
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "c2"
U = UUID(as_uuid=False)
TZ = sa.DateTime(timezone=True)
SEVERITY_CHECK = "IN ('critical','high','medium','low')"


def upgrade() -> None:
    op.create_table(
        "alert_types",
        sa.Column("alert_type_id", sa.SmallInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("category", sa.String(10), nullable=False),
        sa.Column("service_code", sa.String(40), nullable=False),
        sa.Column("trigger_label", sa.String(40), nullable=False),
        sa.Column("default_severity", sa.String(8), nullable=False),
        sa.Column("default_min_confidence", sa.Numeric(3, 2), nullable=False),
        sa.CheckConstraint(
            "category IN ('emergency','safety','security','wellness','system')",
            name="ck_alert_types_category",
        ),
        sa.CheckConstraint(
            f"default_severity {SEVERITY_CHECK}", name="ck_alert_types_default_severity"
        ),
        sa.CheckConstraint(
            "default_min_confidence BETWEEN 0 AND 1",
            name="ck_alert_types_default_min_confidence",
        ),
        schema=S,
    )

    op.create_table(
        "alert_rules",
        sa.Column("rule_id", U, primary_key=True),
        sa.Column("tenant_id", U, nullable=False),
        sa.Column("house_id", U),  # NULL = tenant-wide default
        sa.Column(
            "alert_type_id",
            sa.SmallInteger,
            sa.ForeignKey(f"{S}.alert_types.alert_type_id"),
            nullable=False,
        ),
        sa.Column("trigger_labels", ARRAY(sa.Text), nullable=False),
        sa.Column("min_confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("room_id", U),
        sa.Column("severity", sa.String(8)),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("created_by", U, nullable=False),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", TZ),
        sa.CheckConstraint(
            "cardinality(trigger_labels) >= 1", name="ck_alert_rules_trigger_labels"
        ),
        sa.CheckConstraint("min_confidence BETWEEN 0 AND 1", name="ck_alert_rules_min_confidence"),
        sa.CheckConstraint(f"severity {SEVERITY_CHECK}", name="ck_alert_rules_severity"),
        schema=S,
    )
    # One enabled, non-deleted rule per (tenant, house-or-default, type, room-or-any).
    # Expression index: Alembic cannot reflect it, so it is not declared in the ORM.
    op.execute(
        f"""
        CREATE UNIQUE INDEX ux_rules_dup ON {S}.alert_rules (
          tenant_id,
          COALESCE(house_id, '00000000-0000-0000-0000-000000000000'::uuid),
          alert_type_id,
          COALESCE(room_id, '00000000-0000-0000-0000-000000000000'::uuid)
        ) WHERE is_enabled AND deleted_at IS NULL
        """
    )
    op.create_index(
        "ix_rules_eval",
        "alert_rules",
        ["tenant_id", "house_id"],
        schema=S,
        postgresql_where=sa.text("is_enabled AND deleted_at IS NULL"),
    )

    op.create_table(
        "alerts",
        sa.Column("alert_id", U, primary_key=True),
        sa.Column("tenant_id", U, nullable=False),
        sa.Column("house_id", U, nullable=False),
        sa.Column("room_id", U),
        sa.Column(
            "alert_type_id",
            sa.SmallInteger,
            sa.ForeignKey(f"{S}.alert_types.alert_type_id"),
            nullable=False,
        ),
        sa.Column("rule_id", U, sa.ForeignKey(f"{S}.alert_rules.rule_id"), nullable=False),
        sa.Column("detection_id", U, nullable=False, unique=True),  # idempotency key
        sa.Column("media_id", U, nullable=False),
        sa.Column("top_label", sa.String(40), nullable=False),
        sa.Column("top_confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("severity", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'open'")),
        sa.Column("triggered_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("acknowledged_at", TZ),
        sa.Column("resolved_at", TZ),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(f"severity {SEVERITY_CHECK}", name="ck_alerts_severity"),
        sa.CheckConstraint(
            "status IN ('open','acknowledged','resolved','false_positive')",
            name="ck_alerts_status",
        ),
        schema=S,
    )
    op.create_index(
        "ix_alerts_list",
        "alerts",
        ["house_id", "status", sa.text("triggered_at DESC")],
        schema=S,
    )
    op.create_index("ix_alerts_stats", "alerts", ["tenant_id", "triggered_at"], schema=S)

    op.create_table(
        "alert_status_history",
        sa.Column("history_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "alert_id",
            U,
            sa.ForeignKey(f"{S}.alerts.alert_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(16)),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),  # user id or 'system'
        sa.Column("actor_role", sa.String(20), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("changed_at", TZ, nullable=False, server_default=sa.func.now()),
        schema=S,
    )
    op.create_index("ix_hist_alert", "alert_status_history", ["alert_id", "changed_at"], schema=S)

    op.create_table(
        "notifications",
        sa.Column("notification_id", U, primary_key=True),
        sa.Column("alert_id", U, sa.ForeignKey(f"{S}.alerts.alert_id"), nullable=False),
        sa.Column("contact_id", U),  # NULL for in_app
        sa.Column("channel", sa.String(6), nullable=False),
        sa.Column("recipient", sa.String(254)),
        sa.Column("priority", sa.SmallInteger),
        sa.Column("status", sa.String(7), nullable=False),
        sa.Column("attempt_count", sa.SmallInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("sns_message_id", sa.String(100)),
        sa.Column("last_error", sa.Text),
        sa.Column("next_attempt_at", TZ),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("sent_at", TZ),
        sa.CheckConstraint("channel IN ('in_app','email')", name="ck_notifications_channel"),
        sa.CheckConstraint("status IN ('queued','sent','failed')", name="ck_notifications_status"),
        schema=S,
    )
    op.create_index(
        "ix_notif_retry",
        "notifications",
        ["status", "next_attempt_at"],
        schema=S,
        postgresql_where=sa.text("status = 'failed'"),
    )


def downgrade() -> None:
    # Reverse foreign-key order.
    op.drop_table("notifications", schema=S)
    op.drop_table("alert_status_history", schema=S)
    op.drop_table("alerts", schema=S)
    op.execute(f"DROP INDEX IF EXISTS {S}.ux_rules_dup")
    op.drop_table("alert_rules", schema=S)
    op.drop_table("alert_types", schema=S)
