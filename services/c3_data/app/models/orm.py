"""ORM classes for schema ``c3`` (docs/components/C3_DATABASE_AND_AI.md §2.1).

Must stay in step with ``alembic/versions`` — CI runs ``alembic check``. The partial unique
indexes ``ux_one_active`` (one active model) and ``ux_one_running`` (one running integrity
check per tenant) use ``WHERE`` predicates on an expression, so they live in the migration
and are declared here with ``postgresql_where`` to keep autogenerate in step.

IDs are UUID strings (``as_uuid=False``); JSON columns use JSONB.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


UUIDStr = UUID(as_uuid=False)
TZ = DateTime(timezone=True)


class MlModel(Base):
    __tablename__ = "ml_models"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_ml_models_name_version"),
        CheckConstraint("source IN ('bundled','s3')", name="ck_ml_models_source"),
        CheckConstraint(
            "status IN ('registered','evaluated','active','retired')",
            name="ck_ml_models_status",
        ),
        # Only one row may be active at a time.
        Index(
            "ux_one_active",
            "status",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    model_id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(40))
    version: Mapped[str] = mapped_column(String(20))
    framework: Mapped[str] = mapped_column(String(20), server_default=text("'tensorflow'"))
    source: Mapped[str] = mapped_column(String(10))
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    label_map: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(10))
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(UUIDStr)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    activated_by: Mapped[str | None] = mapped_column(UUIDStr)
    activated_at: Mapped[datetime | None] = mapped_column(TZ)


class ModelEvaluation(Base):
    __tablename__ = "model_evaluations"

    evaluation_id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=_uuid)
    model_id: Mapped[str] = mapped_column(UUIDStr, ForeignKey("ml_models.model_id"), nullable=False)
    dataset: Mapped[str] = mapped_column(String(60))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(TZ)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    created_by: Mapped[str] = mapped_column(UUIDStr)


class IntegrityReport(Base):
    __tablename__ = "integrity_reports"
    __table_args__ = (
        CheckConstraint("status IN ('running','done','failed')", name="ck_integrity_status"),
        # Only one running integrity check per tenant at a time.
        Index(
            "ux_one_running",
            text("(scope->>'tenant_id')"),
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    report_id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=_uuid)
    requested_by: Mapped[str | None] = mapped_column(UUIDStr)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(8))
    findings: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    started_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TZ)


class DataDictionaryVersion(Base):
    __tablename__ = "data_dictionary_versions"

    version: Mapped[str] = mapped_column(String(20), primary_key=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB)
    published_by: Mapped[str] = mapped_column(UUIDStr)
    published_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
