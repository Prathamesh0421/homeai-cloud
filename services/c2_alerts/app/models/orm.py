"""ORM classes for schema ``c2`` (docs/components/C2_ALERT_TRACKING.md §2).

Must stay in step with ``alembic/versions`` — CI runs ``alembic check``. The duplicate-rule
index ``ux_rules_dup`` uses COALESCE expressions, which Alembic cannot reflect, so it lives
only in migration 0001 and is deliberately not declared here.

IDs are UUID strings (``as_uuid=False``); confidences come back as ``float``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


UUIDStr = UUID(as_uuid=False)
TZ = DateTime(timezone=True)


class AlertType(Base):
    __tablename__ = "alert_types"
    __table_args__ = (
        CheckConstraint(
            "category IN ('emergency','safety','security','wellness','system')",
            name="ck_alert_types_category",
        ),
        CheckConstraint(
            "default_severity IN ('critical','high','medium','low')",
            name="ck_alert_types_default_severity",
        ),
        CheckConstraint(
            "default_min_confidence BETWEEN 0 AND 1", name="ck_alert_types_default_min_confidence"
        ),
    )

    alert_type_id: Mapped[int] = mapped_column(
        SmallInteger, Identity(always=True), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(10))
    service_code: Mapped[str] = mapped_column(String(40))
    trigger_label: Mapped[str] = mapped_column(String(40))
    default_severity: Mapped[str] = mapped_column(String(8))
    default_min_confidence: Mapped[float] = mapped_column(Numeric(3, 2, asdecimal=False))


class AlertRule(Base):
    __tablename__ = "alert_rules"
    __table_args__ = (
        CheckConstraint("cardinality(trigger_labels) >= 1", name="ck_alert_rules_trigger_labels"),
        CheckConstraint("min_confidence BETWEEN 0 AND 1", name="ck_alert_rules_min_confidence"),
        CheckConstraint(
            "severity IN ('critical','high','medium','low')", name="ck_alert_rules_severity"
        ),
        Index(
            "ix_rules_eval",
            "tenant_id",
            "house_id",
            postgresql_where=text("is_enabled AND deleted_at IS NULL"),
        ),
    )

    rule_id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(UUIDStr)
    house_id: Mapped[str | None] = mapped_column(UUIDStr)  # NULL = tenant-wide default
    alert_type_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("c2.alert_types.alert_type_id")
    )
    trigger_labels: Mapped[list[str]] = mapped_column(ARRAY(Text))
    min_confidence: Mapped[float] = mapped_column(Numeric(3, 2, asdecimal=False))
    room_id: Mapped[str | None] = mapped_column(UUIDStr)
    severity: Mapped[str | None] = mapped_column(String(8))
    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"), default=1)
    created_by: Mapped[str] = mapped_column(UUIDStr)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(TZ)

    alert_type: Mapped[AlertType] = relationship(lazy="joined")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('critical','high','medium','low')", name="ck_alerts_severity"
        ),
        CheckConstraint(
            "status IN ('open','acknowledged','resolved','false_positive')",
            name="ck_alerts_status",
        ),
        Index("ix_alerts_list", "house_id", "status", text("triggered_at DESC")),
        Index("ix_alerts_stats", "tenant_id", "triggered_at"),
    )

    alert_id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(UUIDStr)
    house_id: Mapped[str] = mapped_column(UUIDStr)
    room_id: Mapped[str | None] = mapped_column(UUIDStr)
    alert_type_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("c2.alert_types.alert_type_id")
    )
    rule_id: Mapped[str] = mapped_column(UUIDStr, ForeignKey("c2.alert_rules.rule_id"))
    detection_id: Mapped[str] = mapped_column(UUIDStr, unique=True)  # idempotency key
    media_id: Mapped[str] = mapped_column(UUIDStr)
    top_label: Mapped[str] = mapped_column(String(40))
    top_confidence: Mapped[float] = mapped_column(Numeric(4, 3, asdecimal=False))
    severity: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'open'"), default="open")
    triggered_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    acknowledged_at: Mapped[datetime | None] = mapped_column(TZ)
    resolved_at: Mapped[datetime | None] = mapped_column(TZ)
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())

    alert_type: Mapped[AlertType] = relationship(lazy="joined")


class AlertStatusHistory(Base):
    __tablename__ = "alert_status_history"
    __table_args__ = (Index("ix_hist_alert", "alert_id", "changed_at"),)

    history_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    alert_id: Mapped[str] = mapped_column(
        UUIDStr, ForeignKey("c2.alerts.alert_id", ondelete="RESTRICT")
    )
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str] = mapped_column(String(64))  # user id or 'system'
    actor_role: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("channel IN ('in_app','email')", name="ck_notifications_channel"),
        CheckConstraint("status IN ('queued','sent','failed')", name="ck_notifications_status"),
        Index(
            "ix_notif_retry",
            "status",
            "next_attempt_at",
            postgresql_where=text("status = 'failed'"),
        ),
    )

    notification_id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=_uuid)
    alert_id: Mapped[str] = mapped_column(UUIDStr, ForeignKey("c2.alerts.alert_id"))
    contact_id: Mapped[str | None] = mapped_column(UUIDStr)  # NULL for in_app
    channel: Mapped[str] = mapped_column(String(6))
    recipient: Mapped[str | None] = mapped_column(String(254))
    priority: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(7))
    attempt_count: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"), default=0)
    sns_message_id: Mapped[str | None] = mapped_column(String(100))
    last_error: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(TZ)
