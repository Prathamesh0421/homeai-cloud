"""C3 initial schema: ml_models, model_evaluations, integrity_reports, data_dictionary_versions.

Matches docs/components/C3_DATABASE_AND_AI.md §2.1. Keep in step with app/models/orm.py
(CI runs ``alembic check``).

Revision ID: 0001
Revises:
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "c3"
U = UUID(as_uuid=False)
TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "ml_models",
        sa.Column("model_id", U, primary_key=True),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column(
            "framework", sa.String(20), nullable=False, server_default=sa.text("'tensorflow'")
        ),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("artifact_uri", sa.Text),
        sa.Column("label_map", JSONB, nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("metrics", JSONB),
        sa.Column("notes", sa.Text),
        sa.Column("created_by", U, nullable=False),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("activated_by", U),
        sa.Column("activated_at", TZ),
        sa.UniqueConstraint("name", "version", name="uq_ml_models_name_version"),
        sa.CheckConstraint("source IN ('bundled','s3')", name="ck_ml_models_source"),
        sa.CheckConstraint(
            "status IN ('registered','evaluated','active','retired')",
            name="ck_ml_models_status",
        ),
        schema=S,
    )
    # Only one row may be active at a time (partial unique index).
    op.create_index(
        "ux_one_active",
        "ml_models",
        ["status"],
        schema=S,
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "model_evaluations",
        sa.Column("evaluation_id", U, primary_key=True),
        sa.Column("model_id", U, sa.ForeignKey(f"{S}.ml_models.model_id"), nullable=False),
        sa.Column("dataset", sa.String(60), nullable=False),
        sa.Column("metrics", JSONB, nullable=False),
        sa.Column("started_at", TZ, nullable=False),
        sa.Column("finished_at", TZ),
        sa.Column("created_by", U, nullable=False),
        schema=S,
    )

    op.create_table(
        "integrity_reports",
        sa.Column("report_id", U, primary_key=True),
        sa.Column("requested_by", U),
        sa.Column("scope", JSONB, nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("findings", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("started_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TZ),
        sa.CheckConstraint("status IN ('running','done','failed')", name="ck_integrity_status"),
        schema=S,
    )
    # Only one running integrity check per tenant at a time (partial unique on an expression).
    op.create_index(
        "ux_one_running",
        "integrity_reports",
        [sa.text("(scope->>'tenant_id')")],
        schema=S,
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "data_dictionary_versions",
        sa.Column("version", sa.String(20), primary_key=True),
        sa.Column("document", JSONB, nullable=False),
        sa.Column("published_by", U, nullable=False),
        sa.Column("published_at", TZ, nullable=False, server_default=sa.func.now()),
        schema=S,
    )


def downgrade() -> None:
    op.drop_table("data_dictionary_versions", schema=S)
    op.execute(f"DROP INDEX IF EXISTS {S}.ux_one_running")
    op.drop_table("integrity_reports", schema=S)
    op.drop_table("model_evaluations", schema=S)
    op.execute(f"DROP INDEX IF EXISTS {S}.ux_one_active")
    op.drop_table("ml_models", schema=S)
