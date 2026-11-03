"""Seed the 7 alert types (docs/02_CONTRACTS.md §3 mapping table).

Values are frozen here on purpose (migrations must not import app code that may change).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# code, name, category, service_code, trigger_label, default_severity, default_min_confidence
ALERT_TYPES = [
    ("smoke", "Smoke alarm", "emergency", "fire_safety", "smoke_alarm", "critical", 0.50),
    ("distress", "Distress sound", "emergency", "distress", "distress_sound", "critical", 0.60),
    ("intrusion", "Glass break", "security", "intrusion", "glass_break", "high", 0.55),
    ("fall", "Possible fall", "safety", "fall", "fall_indicator", "high", 0.65),
    ("wellness_cough", "Coughing", "wellness", "wellness", "cough", "low", 0.55),
    ("presence", "Speech detected", "wellness", "presence", "speech", "low", 0.50),
    ("pet", "Dog barking", "wellness", "pet", "dog", "low", 0.55),
]

alert_types = sa.table(
    "alert_types",
    sa.column("code", sa.String),
    sa.column("name", sa.String),
    sa.column("category", sa.String),
    sa.column("service_code", sa.String),
    sa.column("trigger_label", sa.String),
    sa.column("default_severity", sa.String),
    sa.column("default_min_confidence", sa.Numeric),
    schema="c2",
)


def upgrade() -> None:
    keys = [
        "code",
        "name",
        "category",
        "service_code",
        "trigger_label",
        "default_severity",
        "default_min_confidence",
    ]
    op.bulk_insert(alert_types, [dict(zip(keys, row, strict=True)) for row in ALERT_TYPES])


def downgrade() -> None:
    codes = [row[0] for row in ALERT_TYPES]
    op.execute(alert_types.delete().where(alert_types.c.code.in_(codes)))
