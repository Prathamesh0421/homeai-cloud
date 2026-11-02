"""Unit tests for the lockout window logic in user_repo."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.models.orm import Tenant, User
from app.repositories import user_repo
from sqlalchemy.orm import Session


def _make_user(session: Session) -> User:
    tenant = Tenant(name=f"t-{uuid4()}", timezone="UTC")
    session.add(tenant)
    session.flush()
    user = User(
        tenant_id=tenant.tenant_id,
        email=f"u-{uuid4()}@homeai.test",
        password_hash="x",
        role="house_owner",
    )
    session.add(user)
    session.flush()
    return user


def test_first_failure_starts_window(db_session):
    user = _make_user(db_session)
    now = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
    user_repo.record_failed_attempt(
        db_session,
        user,
        failure_threshold=5,
        window_seconds=900,
        lockout_seconds=900,
        now=now,
    )
    assert user.failed_attempts == 1
    assert user.first_failed_at == now
    assert user.locked_until is None


def test_locks_after_threshold(db_session):
    user = _make_user(db_session)
    base = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
    for i in range(4):
        user_repo.record_failed_attempt(
            db_session,
            user,
            failure_threshold=5,
            window_seconds=900,
            lockout_seconds=900,
            now=base + timedelta(seconds=i * 10),
        )
    assert user.failed_attempts == 4
    assert user.locked_until is None
    user_repo.record_failed_attempt(
        db_session,
        user,
        failure_threshold=5,
        window_seconds=900,
        lockout_seconds=900,
        now=base + timedelta(seconds=50),
    )
    assert user.failed_attempts == 5
    assert user.locked_until is not None
    assert user.locked_until > base


def test_window_resets_after_15_minutes(db_session):
    user = _make_user(db_session)
    base = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
    user_repo.record_failed_attempt(
        db_session,
        user,
        failure_threshold=5,
        window_seconds=900,
        lockout_seconds=900,
        now=base,
    )
    # 20 minutes later: window should reset.
    user_repo.record_failed_attempt(
        db_session,
        user,
        failure_threshold=5,
        window_seconds=900,
        lockout_seconds=900,
        now=base + timedelta(seconds=1200),
    )
    assert user.failed_attempts == 1
    assert user.locked_until is None


def test_reset_lockout_clears_counters(db_session):
    user = _make_user(db_session)
    user.failed_attempts = 4
    user.first_failed_at = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
    user_repo.reset_lockout(db_session, user)
    assert user.failed_attempts == 0
    assert user.first_failed_at is None
    assert user.locked_until is None
