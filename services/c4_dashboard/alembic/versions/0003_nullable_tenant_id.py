"""Allow NULL tenant_id for platform staff (cloud_staff).

Cloud-staff users are platform-level, not tied to a tenant, so users.tenant_id
must be nullable. The users_public view already projects tenant_id as-is.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "tenant_id",
        existing_type=sa.UUID(),
        nullable=True,
        schema="c4",
    )


def downgrade() -> None:
    # Backfill nulls to a sentinel tenant before re-adding NOT NULL is the
    # caller's responsibility; we only restore the constraint.
    op.alter_column(
        "users",
        "tenant_id",
        existing_type=sa.UUID(),
        nullable=False,
        schema="c4",
    )
