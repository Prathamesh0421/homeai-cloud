"""Revoked-token denylist (C4 enforces strictly; other services cache)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import RevokedToken


def revoke(session: Session, jti: UUID, expires_at: datetime) -> None:
    existing = session.get(RevokedToken, jti)
    if existing is None:
        session.add(RevokedToken(jti=jti, expires_at=expires_at))


def is_revoked(session: Session, jti: UUID) -> bool:
    return session.get(RevokedToken, jti) is not None


def list_revoked_since(session: Session, since: datetime) -> list[str]:
    stmt = select(RevokedToken.jti).where(RevokedToken.expires_at >= since)
    return [str(row[0]) for row in session.execute(stmt)]


def purge_expired(session: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    stmt = select(RevokedToken).where(RevokedToken.expires_at < now)
    count = 0
    for row in session.scalars(stmt):
        session.delete(row)
        count += 1
    return count
