"""Seed the active model ``yamnet 1.0.0`` with the default 7-label map.

Label map matches docs/components/C3_DATABASE_AND_AI.md §2.3 (source classes must match
YAMNet display names exactly). Values are frozen here on purpose — migrations must not import
app code that may change. ``created_by`` is the nil UUID (system/bootstrap seed); it is a bare
UUID column with no FK to C4 users, so no dependency on C4's seed.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

U = UUID(as_uuid=False)

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NIL_UUID = "00000000-0000-0000-0000-000000000000"
MODEL_ID = "a0000000-0000-4000-8000-000000000001"  # fixed so docs/demos can reference it

# home_label, category, source_classes, min_confidence, rule
LABEL_ENTRIES = [
    {
        "home_label": "smoke_alarm",
        "category": "emergency",
        "source_classes": [
            "Smoke detector, smoke alarm",
            "Fire alarm",
            "Alarm",
            "Beep, bleep",
        ],
        "min_confidence": 0.50,
        "rule": "max",
    },
    {
        "home_label": "distress_sound",
        "category": "emergency",
        "source_classes": [
            "Screaming",
            "Shout",
            "Yell",
            "Crying, sobbing",
            "Baby cry, infant cry",
        ],
        "min_confidence": 0.60,
        "rule": "consec2",
    },
    {
        "home_label": "glass_break",
        "category": "security",
        "source_classes": ["Glass", "Shatter", "Breaking"],
        "min_confidence": 0.55,
        "rule": "max",
    },
    {
        "home_label": "fall_indicator",
        "category": "safety",
        "source_classes": ["Thump, thud", "Bang", "Slam"],
        "min_confidence": 0.65,
        "rule": "consec2",
    },
    {
        "home_label": "cough",
        "category": "wellness",
        "source_classes": ["Cough", "Throat clearing"],
        "min_confidence": 0.55,
        "rule": "mean",
    },
    {
        "home_label": "speech",
        "category": "wellness",
        "source_classes": ["Speech", "Conversation"],
        "min_confidence": 0.50,
        "rule": "mean",
    },
    {
        "home_label": "dog",
        "category": "wellness",
        "source_classes": ["Dog", "Bark"],
        "min_confidence": 0.55,
        "rule": "max",
    },
]

LABEL_MAP = {"version": "1.0.0", "entries": LABEL_ENTRIES}

ml_models = sa.table(
    "ml_models",
    sa.column("model_id", U),
    sa.column("name", sa.String),
    sa.column("version", sa.String),
    sa.column("framework", sa.String),
    sa.column("source", sa.String),
    sa.column("label_map", JSONB),
    sa.column("status", sa.String),
    sa.column("created_by", U),
    schema="c3",
)


def upgrade() -> None:
    op.bulk_insert(
        ml_models,
        [
            {
                "model_id": MODEL_ID,
                "name": "yamnet",
                "version": "1.0.0",
                "framework": "tensorflow",
                "source": "bundled",
                "label_map": LABEL_MAP,
                "status": "active",
                "created_by": NIL_UUID,
            }
        ],
    )


def downgrade() -> None:
    op.execute(ml_models.delete().where(ml_models.c.model_id == MODEL_ID))
