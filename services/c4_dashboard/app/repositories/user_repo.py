"""User repository."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import User


def get_by_email(session: Session, email: str) -> User | None:
    stmt = select(User).where(User.email == email.lower())
    return session.scalars(stmt).first()


def get_by_id(session: Session, user_id: UUID) -> User | None:
    return session.get(User, user_id)


def record_failed_attempt(
    session: Session,
    user: User,
    *,
    failure_threshold: int,
    window_seconds: int,
    lockout_seconds: int,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(UTC)
    if (
        user.first_failed_at is None
        or (now - user.first_failed_at).total_seconds() > window_seconds
    ):
        user.first_failed_at = now
        user.failed_attempts = 0
    user.failed_attempts += 1
    if user.failed_attempts >= failure_threshold:
        user.locked_until = datetime.fromtimestamp(now.timestamp() + lockout_seconds, tz=UTC)


def reset_lockout(session: Session, user: User) -> None:
    user.failed_attempts = 0
    user.first_failed_at = None
    user.locked_until = None


def touch_last_login(session: Session, user: User, now: datetime | None = None) -> None:
    user.last_login_at = now or datetime.now(UTC)
