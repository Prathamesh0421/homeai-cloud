"""Rate-limit counters in Postgres so the limit holds across C2 copies (S-5).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_hits",
        sa.Column("bucket", sa.String(32), primary_key=True),
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("hits", sa.Integer, nullable=False),
        schema="c2",
    )
    op.create_index("ix_rate_limit_window", "rate_limit_hits", ["window_start"], schema="c2")


def downgrade() -> None:
    op.drop_table("rate_limit_hits", schema="c2")
