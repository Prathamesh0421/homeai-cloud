"""C2-10: NotificationRetry and the advisory lock / JobRunner against Postgres."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from app.gateways.types import Contact
from app.jobs import notification_retry as retry_mod
from app.jobs.lock import RETRY_LOCK, SYNC_LOCK, advisory_lock
from app.jobs.notification_retry import NotificationRetry
from app.jobs.runner import JobRunner
from app.models.orm import Notification
from app.services.notification_service import NotificationService
from app.services.signed_link import KeyRing, SignedLinkService

from tests.factories import (
    BATH,
    HOUSE_A1,
    HOUSE_A2,
    KITCHEN,
    MAPLE,
    ROOM_A1_KITCHEN,
    make_alert,
    make_rule,
)
from tests.fakes import FakeHouseReader, FakeNotifier, FakeSettingsReader

NOW = datetime(2026, 10, 25, 6, 20, tzinfo=UTC)
TRIGGERED = datetime(2026, 10, 25, 6, 10, tzinfo=UTC)
DANA = Contact("55555555-0000-4000-8000-000000000001", "Dana", "dana@example.com", "family", 1)
CAM = Contact("55555555-0000-4000-8000-000000000002", "Cam", "cam@example.com", "caregiver", 2)
LINKS = SignedLinkService(
    keys=lambda: KeyRing("k1", {"k1": b"k" * 32}), public_base_url="https://homeai.example"
)


@pytest.fixture
def notifier():
    return FakeNotifier()


@pytest.fixture
def contacts():
    return FakeSettingsReader(contacts={HOUSE_A1: [DANA, CAM]})


@pytest.fixture
def service(session, notifier, contacts):
    return NotificationService(
        session=session,
        notifier=notifier,
        links=LINKS,
        contacts=contacts,
        houses=FakeHouseReader([MAPLE], [BATH, KITCHEN]),
        clock=lambda: NOW,
    )


@pytest.fixture
def alert(session):
    return new_alert(session)


def new_alert(session, *, house_id=HOUSE_A1, status="open"):
    if "rule" not in session.info:  # one tenant default rule per test
        session.info["rule"] = make_rule(session, "intrusion")
    return make_alert(
        session,
        session.info["rule"],
        house_id=house_id,
        room_id=ROOM_A1_KITCHEN if house_id == HOUSE_A1 else None,
        severity="high",
        status=status,
        triggered_at=TRIGGERED,
    )


def email_row(session, alert, contact=DANA, *, status="failed", attempts=1, due=True, **kw):
    row = Notification(
        alert_id=alert.alert_id,
        contact_id=contact.contact_id,
        channel="email",
        recipient=contact.email,
        priority=contact.priority,
        status=status,
        attempt_count=attempts,
        last_error="subscription_pending" if status == "failed" else None,
        next_attempt_at=(NOW - timedelta(seconds=1) if due else NOW + timedelta(minutes=1))
        if status == "failed"
        else None,
        created_at=kw.pop("created_at", NOW - timedelta(minutes=2)),
        **kw,
    )
    session.add(row)
    session.commit()  # stored, as the job finds rows (a rollback in the job must not undo them)
    return row


def run(service, **kw):
    return NotificationRetry(service, **kw).run()


# --- what is due ----------------------------------------------------------------------------


def test_only_due_email_rows_are_retried(session, service, notifier, alert):
    due = email_row(session, alert)
    stuck = email_row(
        session, alert, CAM, status="queued", attempts=0, created_at=NOW - timedelta(minutes=6)
    )
    other = new_alert(session)
    email_row(session, other, due=False)  # not yet
    email_row(session, other, CAM, attempts=3)  # out of attempts
    email_row(session, other, status="queued", attempts=0, created_at=NOW - timedelta(minutes=4))
    email_row(session, other, CAM, status="sent", attempts=1)
    given_up = email_row(session, other)
    given_up.next_attempt_at = None
    session.add(Notification(alert_id=alert.alert_id, channel="in_app", status="failed"))
    session.flush()

    result = run(service)
    assert (result.due, result.sent) == (2, 2)
    assert {p["contact_id"] for p in notifier.published} == {DANA.contact_id, CAM.contact_id}
    assert (due.status, due.attempt_count, due.last_error) == ("sent", 2, None)
    assert due.sns_message_id.startswith("msg-")
    assert (stuck.status, stuck.attempt_count) == ("sent", 1)  # a crash left it unsent


def test_nothing_due(service):
    assert run(service).due == 0


def test_batch_size_is_capped(session, service, alert):
    for _ in range(3):
        email_row(session, alert)
    assert run(service, batch=2).due == 2


# --- outcomes -------------------------------------------------------------------------------


def test_still_pending_backs_off_then_gives_up(session, service, notifier, alert):
    notifier.pending.add(DANA.email)
    row = email_row(session, alert)
    result = run(service)
    assert result.failed == 1
    assert (row.attempt_count, row.last_error) == (2, "subscription_pending")
    assert row.next_attempt_at == NOW + timedelta(minutes=2)

    row.next_attempt_at = NOW - timedelta(seconds=1)
    run(service)
    assert (row.status, row.attempt_count, row.next_attempt_at) == ("failed", 3, None)
    assert run(service).due == 0  # three attempts in total


def test_removed_contact_is_given_up(session, service, contacts, notifier, alert):
    row = email_row(session, alert, CAM)
    contacts._contacts[HOUSE_A1] = [DANA]
    result = run(service)
    assert result.stopped == 1
    assert (row.status, row.last_error, row.next_attempt_at, row.attempt_count) == (
        "failed",
        "contact_removed",
        None,
        1,
    )
    assert notifier.published == []


def test_changed_email_goes_to_the_current_address(session, service, contacts, notifier, alert):
    topic = notifier.ensure_topic(HOUSE_A1)
    notifier.ensure_subscription(topic, DANA.email, DANA.contact_id)  # old address, confirmed
    row = email_row(session, alert)
    moved = Contact(DANA.contact_id, "Dana", "dana@new.example", "family", 1)
    contacts._contacts[HOUSE_A1] = [moved]
    run(service)
    assert (row.status, row.recipient) == ("sent", "dana@new.example")
    # The old address no longer receives Dana's emails (same contact_id filter policy).
    assert notifier.subscribed[topic].keys() == {"dana@new.example"}


@pytest.mark.parametrize("status", ["false_positive", "resolved"])
def test_closed_alert_is_not_emailed_again(session, service, notifier, status):
    row = email_row(session, new_alert(session, status=status))
    assert run(service).stopped == 1
    assert (row.last_error, row.next_attempt_at) == ("alert_closed", None)
    assert notifier.published == []


def test_acknowledged_alert_is_still_emailed(session, service, notifier):
    row = email_row(session, new_alert(session, status="acknowledged"))
    run(service)
    assert row.status == "sent"


def test_c4_down_defers_without_using_an_attempt(session, service, contacts, alert):
    row = email_row(session, alert)
    contacts.down = True
    result = run(service)
    assert (result.deferred, result.failed) == (1, 0)
    assert (row.status, row.attempt_count) == ("failed", 1)


def test_one_bad_row_does_not_stop_the_batch(session, service, notifier, alert, monkeypatch):
    first = email_row(session, alert)
    second = email_row(session, alert, CAM)
    real = service.deliver

    def deliver(row, alert, contact):
        if row is first:
            raise RuntimeError("boom")
        return real(row, alert, contact)

    monkeypatch.setattr(service, "deliver", deliver)
    result = run(service)
    assert (result.failed, result.sent, result.errors) == (1, 1, [first.notification_id])
    assert second.status == "sent"
    assert (first.status, first.attempt_count, first.last_error) == (
        "failed",
        2,
        "error: RuntimeError",
    )


def test_a_row_that_always_breaks_ends_failed(session, service, alert, monkeypatch):
    row = email_row(session, alert)

    def deliver(row, alert, contact):
        raise ValueError("bad data")

    monkeypatch.setattr(service, "deliver", deliver)
    for _ in range(3):
        run(service)
        if row.next_attempt_at is not None:
            row.next_attempt_at = NOW - timedelta(seconds=1)
    assert (row.status, row.attempt_count, row.next_attempt_at) == ("failed", 3, None)
    assert run(service).due == 0


def test_database_trouble_while_recording_defers(session, service, alert, monkeypatch):
    email_row(session, alert)
    monkeypatch.setattr(service, "deliver", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))

    def broken(row, error):
        raise RuntimeError("database down")

    monkeypatch.setattr(service, "record_failure", broken)
    result = run(service)
    assert (result.deferred, result.failed) == (1, 0)


def test_houses_are_read_once_each(session, service, contacts, alert, monkeypatch):
    for contact in (DANA, CAM):
        email_row(session, alert, contact)
    email_row(session, new_alert(session, house_id=HOUSE_A2), DANA)  # contact no longer there
    calls = []
    real = contacts.contacts
    monkeypatch.setattr(contacts, "contacts", lambda h: calls.append(h) or real(h))
    result = run(service)
    assert sorted(calls) == sorted([HOUSE_A1, HOUSE_A2])
    assert (result.sent, result.stopped) == (2, 1)


def test_retry_constants_match_the_plan():
    assert timedelta(minutes=5) == retry_mod.STUCK_AFTER
    assert {"false_positive", "resolved"} == retry_mod.CLOSED


# --- advisory lock and JobRunner ------------------------------------------------------------


def test_lock_is_exclusive_and_released(pg_engine):
    with advisory_lock(pg_engine, RETRY_LOCK) as first:
        assert first is True
        with advisory_lock(pg_engine, RETRY_LOCK) as second:
            assert second is False
        with advisory_lock(pg_engine, SYNC_LOCK) as other_job:
            assert other_job is True
    with advisory_lock(pg_engine, RETRY_LOCK) as again:
        assert again is True


def test_lock_is_released_when_the_job_fails(pg_engine):
    with pytest.raises(RuntimeError), advisory_lock(pg_engine, RETRY_LOCK):
        raise RuntimeError("job crashed")
    with advisory_lock(pg_engine, RETRY_LOCK) as held:
        assert held is True


@pytest.fixture
def runner(pg_engine, session, notifier):
    @contextmanager
    def scope():
        yield session

    return JobRunner(
        notifier=notifier,
        links=LINKS,
        lock_engine=lambda: pg_engine,
        primary=scope,
        reader=scope,
        clock=lambda: NOW,
    )


def test_runner_retry_uses_the_real_gateways(runner, session, alert):
    from tests.db.foreign_tables import seed

    seed(session)  # c4/c1 tables for the real gateways (DANA is not among them)
    row = email_row(session, alert)
    result = runner.retry()
    assert result.stopped == 1  # contact unknown to C4
    assert row.last_error == "contact_removed"


def test_runner_skips_while_another_process_runs_the_job(runner, pg_engine):
    with advisory_lock(pg_engine, RETRY_LOCK):
        assert runner.retry() is None
    with advisory_lock(pg_engine, SYNC_LOCK):
        assert runner.sync() is None


def test_runner_sync_over_real_gateways(runner, session, notifier):
    from tests.db.foreign_tables import CONTACTS, seed

    seed(session)
    result = runner.sync()
    assert (result.topics, result.subscribed, result.failed) == (1, len(CONTACTS), 0)
    assert runner.sync(HOUSE_A2).topics == 0  # no contacts and no topic


# STANDIN(C1-02): relies on the test database having no c4 tables; once the real C1/C4
# migrations build them, seed a contact there and assert a real sync result instead.
@pytest.mark.usefixtures("pg_engine")  # skip (or fail on CI) without Postgres, like the others
def test_default_wiring_uses_the_configured_databases():
    """JobRunner as create_app builds it: db.session_scope, the c2_reader engine, its own lock."""
    from app.gateways.notifier import LogNotifier
    from app.gateways.types import DependencyUnavailableError
    from homeai_common import db

    from tests.db.conftest import DATABASE_URL

    db.configure_db(DATABASE_URL, reader_url=DATABASE_URL)
    try:
        runner = JobRunner(notifier=LogNotifier(), links=LINKS)
        assert runner.retry().due == 0
        # No c4 tables outside a test transaction: the reader reports C4 as unavailable.
        with pytest.raises(DependencyUnavailableError, match="c4"):
            runner.sync()
    finally:
        db.dispose_db()
