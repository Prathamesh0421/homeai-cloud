"""Tenant repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import Tenant


def get_by_id(session: Session, tenant_id: UUID) -> Tenant | None:
    return session.get(Tenant, tenant_id)


def list_all(session: Session) -> list[Tenant]:
    return list(session.scalars(select(Tenant).order_by(Tenant.created_at)))
