"""C2-10: ContactSubscriptionSync with fake contacts and SNS, plus the scheduler wiring."""

from __future__ import annotations

import logging

import pytest
from app.gateways.notifier import LogNotifier
from app.gateways.types import Contact, DependencyUnavailableError
from app.jobs import runner as runner_mod
from app.jobs.subscription_sync import SubscriptionSync

from tests.factories import HOUSE_A1, HOUSE_A2, HOUSE_B1
from tests.fakes import FakeNotifier, FakeSettingsReader

DANA = Contact("55555555-0000-4000-8000-000000000001", "Dana", "dana@example.com", "family", 1)
CAM = Contact("55555555-0000-4000-8000-000000000002", "Cam", "Cam@Example.com", "caregiver", 2)
NED = Contact("55555555-0000-4000-8000-000000000003", "Ned", "ned@example.com", "neighbor", 3)


@pytest.fixture
def notifier():
    return FakeNotifier()


@pytest.fixture
def contacts():
    return FakeSettingsReader(contacts={HOUSE_A1: [DANA, CAM], HOUSE_B1: [NED]})


def sync(contacts, notifier, house_id=None):
    return SubscriptionSync(contacts, notifier).run(house_id)


def test_every_contact_gets_a_subscription(contacts, notifier):
    result = sync(contacts, notifier)
    assert (result.topics, result.subscribed, result.pending, result.removed) == (2, 3, 0, 0)
    assert notifier.subscribed[notifier.topics[HOUSE_A1]].keys() == {
        "dana@example.com",
        "cam@example.com",
    }


def test_pending_confirmations_are_counted(contacts, notifier, caplog):
    notifier.pending.add(NED.email)
    with caplog.at_level(logging.INFO):
        result = sync(contacts, notifier)
    assert (result.subscribed, result.pending) == (2, 1)
    assert "ned@example.com" not in caplog.text  # emails are masked in logs


def test_unsubscribed_contacts_are_counted_and_the_house_still_syncs(contacts, notifier, caplog):
    notifier.opted_out.add(CAM.email)
    with caplog.at_level(logging.INFO):
        result = sync(contacts, notifier)
    assert (result.subscribed, result.pending, result.unsubscribed, result.failed) == (2, 0, 1, 0)
    assert "contact unsubscribed" in caplog.text
    assert "cam@example.com" not in caplog.text.lower()  # emails are masked in logs


def test_former_contacts_are_unsubscribed(contacts, notifier):
    sync(contacts, notifier)
    contacts._contacts[HOUSE_A1] = [CAM]  # Dana removed in C4
    result = sync(contacts, notifier)
    assert result.removed == 1
    topic = notifier.topics[HOUSE_A1]
    assert notifier.unsubscribed == [f"{topic}:{DANA.contact_id}"]
    assert notifier.subscribed[topic].keys() == {"cam@example.com"}  # case-insensitive match


def test_house_with_no_contacts_left_is_cleaned_through_its_topic(contacts, notifier):
    sync(contacts, notifier)
    del contacts._contacts[HOUSE_B1]
    result = sync(contacts, notifier)
    assert (result.topics, result.removed) == (2, 1)
    assert notifier.subscribed[notifier.topics[HOUSE_B1]] == {}


def test_pending_former_contact_is_left_to_lapse(contacts, notifier):
    notifier.pending.add(NED.email)
    sync(contacts, notifier)
    contacts._contacts[HOUSE_B1] = []
    result = sync(contacts, notifier)
    assert result.removed == 0
    assert notifier.unsubscribed == []  # AWS cannot unsubscribe "PendingConfirmation"


def test_no_topic_is_created_for_a_house_without_contacts(contacts, notifier):
    result = sync(contacts, notifier, HOUSE_A2)
    assert (result.topics, notifier.topics) == (0, {})


def test_one_house(contacts, notifier):
    result = sync(contacts, notifier, HOUSE_B1)
    assert (result.topics, result.subscribed) == (1, 1)
    assert set(notifier.topics) == {HOUSE_B1}


def test_sns_failure_skips_only_that_house(contacts, notifier):
    notifier.fail_houses.add(HOUSE_A1)
    result = sync(contacts, notifier)
    assert (result.topics, result.subscribed, result.failed) == (1, 1, 1)


def test_listing_topics_fails(contacts, notifier, monkeypatch):
    def down():
        raise notifier._error("sns list_topics failed: Throttling")

    monkeypatch.setattr(notifier, "house_topics", down)
    result = sync(contacts, notifier)
    assert (result.failed, result.topics) == (1, 0)


def test_c4_down_raises(contacts, notifier):
    contacts.down = True
    with pytest.raises(DependencyUnavailableError):
        sync(contacts, notifier)


def test_log_notifier_sync_is_a_no_op(contacts):
    result = sync(contacts, LogNotifier())
    assert (result.topics, result.subscribed, result.removed) == (2, 3, 0)
    LogNotifier().unsubscribe("arn:x")  # nothing to do


# --- scheduler ------------------------------------------------------------------------------


class _Runner:
    def __init__(self):
        self.calls = []

    def retry(self):
        self.calls.append("retry")

    def sync(self):
        raise RuntimeError("sns down")


def test_scheduler_runs_both_jobs_on_their_intervals():
    scheduler = runner_mod.start_scheduler(_Runner())
    try:
        jobs = {j.id: j.trigger.interval.total_seconds() for j in scheduler.get_jobs()}
        assert jobs == {"notification_retry": 60, "subscription_sync": 300}
        assert all(j.max_instances == 1 and j.coalesce for j in scheduler.get_jobs())
    finally:
        scheduler.shutdown(wait=False)


def test_a_failing_run_is_logged_not_raised(caplog):
    runner = _Runner()
    with caplog.at_level(logging.ERROR):
        runner_mod._logged("subscription_sync", runner.sync)()
        runner_mod._logged("notification_retry", runner.retry)()
    assert runner.calls == ["retry"]
    assert "job failed" in caplog.text


def test_reader_scope_without_a_reader_database(monkeypatch):
    from homeai_common import db

    monkeypatch.setattr(db, "_engines", {})
    with pytest.raises(DependencyUnavailableError, match="c2_reader"), runner_mod.reader_scope():
        pass


def test_app_starts_and_stops_the_scheduler(settings, monkeypatch):
    from app.main import create_app
    from fastapi.testclient import TestClient

    events = []

    class _Scheduler:
        def shutdown(self, wait):
            events.append(("shutdown", wait))

    def start(runner):
        events.append(("start", runner))
        return _Scheduler()

    monkeypatch.setattr("app.main.start_scheduler", start)
    app = create_app(settings.model_copy(update={"jobs_enabled": True}), checks={})
    with TestClient(app):
        pass
    assert events == [("start", app.state.jobs), ("shutdown", True)]

    events.clear()
    with TestClient(create_app(settings, checks={})):  # jobs_enabled=False in tests
        pass
    assert events == []
