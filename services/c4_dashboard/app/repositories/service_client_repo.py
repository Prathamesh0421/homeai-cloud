"""Service client repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import ServiceClient


def get(session, client_id: str) -> ServiceClient | None:
    return session.get(ServiceClient, client_id)


def list_active(session: Session) -> list[ServiceClient]:
    stmt = select(ServiceClient).where(ServiceClient.is_active.is_(True))
    return list(session.scalars(stmt))
