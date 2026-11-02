"""C4 initial schema: tenants, users, users_public view, service_clients, revoked_tokens,
house_service_settings, emergency_contacts.

Revision ID: 0001
Revises:
Create Date: 2026-11-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS c4")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "tenants",
        sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("timezone", sa.String(40), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema="c4",
    )

    op.create_table(
        "users",
        sa.Column("user_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", UUID(as_uuid=True), sa.ForeignKey("c4.tenants.tenant_id"), nullable=False
        ),
        sa.Column("email", CITEXT, nullable=False, unique=True),
        sa.Column("password_hash", sa.String(100), nullable=False),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("display_name", sa.String(80)),
        sa.Column("house_ids", ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("failed_attempts", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("first_failed_at", sa.DateTime(timezone=True)),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "role IN ('house_owner','iot_staff','cloud_staff')", name="users_role_check"
        ),
        schema="c4",
    )

    op.execute(
        "CREATE VIEW c4.users_public AS SELECT user_id, tenant_id, email, role, display_name, "
        "house_ids, is_active, created_at, last_login_at FROM c4.users"
    )

    op.create_table(
        "service_clients",
        sa.Column("client_id", sa.String(40), primary_key=True),
        sa.Column("secret_hash", sa.String(100), nullable=False),
        sa.Column("scopes", ARRAY(sa.Text), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        schema="c4",
    )

    op.create_table(
        "revoked_tokens",
        sa.Column("jti", UUID(as_uuid=True), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        schema="c4",
    )

    op.create_table(
        "house_service_settings",
        sa.Column("house_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", UUID(as_uuid=True), sa.ForeignKey("c4.tenants.tenant_id"), nullable=False
        ),
        sa.Column("enabled_services", ARRAY(sa.Text), nullable=False),
        sa.Column("quiet_start", sa.Time),
        sa.Column("quiet_end", sa.Time),
        sa.Column("sensitivity", sa.String(6), nullable=False, server_default="medium"),
        sa.Column("updated_by", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "(quiet_start IS NULL) = (quiet_end IS NULL)", name="quiet_both_or_neither"
        ),
        sa.CheckConstraint(
            "sensitivity IN ('low','medium','high')", name="settings_sensitivity_check"
        ),
        schema="c4",
    )

    op.create_table(
        "emergency_contacts",
        sa.Column("contact_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("house_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("phone", sa.String(20)),
        sa.Column("contact_type", sa.String(20), nullable=False),
        sa.Column("priority", sa.SmallInteger, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "contact_type IN ('family','caregiver','neighbor','emergency_service')",
            name="contacts_type_check",
        ),
        sa.CheckConstraint("priority BETWEEN 1 AND 5", name="contacts_priority_check"),
        sa.UniqueConstraint("house_id", "email", name="contacts_house_email_unique"),
        schema="c4",
    )
    # DEFERRABLE INITIALLY DEFERRED so reorder can swap priorities within a tx.
    op.execute(
        "ALTER TABLE c4.emergency_contacts "
        "ADD CONSTRAINT contacts_house_priority_unique UNIQUE (house_id, priority) "
        "DEFERRABLE INITIALLY DEFERRED"
    )


def downgrade() -> None:
    op.drop_table("emergency_contacts", schema="c4")
    op.drop_table("house_service_settings", schema="c4")
    op.drop_table("revoked_tokens", schema="c4")
    op.drop_table("service_clients", schema="c4")
    op.execute("DROP VIEW IF EXISTS c4.users_public")
    op.drop_table("users", schema="c4")
    op.drop_table("tenants", schema="c4")
