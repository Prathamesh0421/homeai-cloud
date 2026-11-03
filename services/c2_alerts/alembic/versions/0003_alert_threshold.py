"""Store the effective threshold an alert was raised at (rule min_confidence + sensitivity).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("threshold", sa.Numeric(3, 2)), schema="c2")


def downgrade() -> None:
    op.drop_column("alerts", "threshold", schema="c2")
