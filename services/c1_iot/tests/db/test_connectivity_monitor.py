"""C1-08: ConnectivityMonitor against Postgres — same rows as ``derive`` (plan §4.2)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta

from app.jobs.connectivity_monitor import CONNECTIVITY_LOCK, advisory_lock, run_once
from app.models import CameraFeed, House
from app.services.connectivity import ConnectivityMonitor

from tests.factories import HOUSE_A1, NOW, ROOM_A1_BATH, ROOM_A1_KITCHEN, make_feed


def feeds(seeded):
    maple = seeded.get(House, HOUSE_A1)
    rows = {
        "never": make_feed(maple, ROOM_A1_KITCHEN, is_enabled=True, connectivity_status="online"),
        "fresh": make_feed(maple, ROOM_A1_KITCHEN, is_enabled=True, last_clip_at=NOW - timedelta(seconds=10)),
        "stale": make_feed(
            maple, ROOM_A1_BATH, is_enabled=True, status="active", connectivity_status="online",
            last_clip_at=NOW - timedelta(seconds=45),
        ),
        "error_fresh": make_feed(maple, ROOM_A1_BATH, is_enabled=True, status="error", last_clip_at=NOW),
        "disabled": make_feed(maple, ROOM_A1_BATH, is_enabled=False, last_clip_at=NOW - timedelta(days=1)),
        "short_interval": make_feed(
            maple, ROOM_A1_BATH, is_enabled=True, last_clip_at=NOW - timedelta(seconds=10),
            config={"capture_interval_s": 5, "sensitivity": "low", "network_label": None},
        ),
    }  # fmt: skip
    seeded.add_all(rows.values())
    seeded.flush()
    return rows


def state(seeded, feed) -> tuple[str, str]:
    f = seeded.get(CameraFeed, feed.feed_id)
    return f.connectivity_status, f.status


def test_monitor_applies_each_row(seeded):
    rows = feeds(seeded)
    result = ConnectivityMonitor(seeded).run(NOW)
    seeded.expire_all()
    assert state(seeded, rows["never"]) == ("unknown", "provisioned")
    assert state(seeded, rows["fresh"]) == ("online", "active")
    assert state(seeded, rows["stale"]) == ("offline", "inactive")
    assert state(seeded, rows["error_fresh"]) == ("online", "error")
    assert state(seeded, rows["disabled"]) == ("unknown", "provisioned")  # not monitored
    assert state(seeded, rows["short_interval"]) == ("offline", "inactive")
    assert (result.unknown, result.online, result.offline) == (1, 2, 2)


def test_second_run_changes_nothing(seeded):
    feeds(seeded)
    ConnectivityMonitor(seeded).run(NOW)
    again = ConnectivityMonitor(seeded).run(NOW)
    assert (again.unknown, again.online, again.offline) == (0, 0, 0)


def test_run_once_takes_the_lock_and_skips_when_held(pg_engine, seeded):
    feeds(seeded)

    @contextmanager
    def same_session():
        yield seeded

    result = run_once(lock_engine=lambda: pg_engine, session_scope=same_session, clock=lambda: NOW)
    assert result is not None
    assert result.online == 2

    with advisory_lock(pg_engine, CONNECTIVITY_LOCK) as held:
        assert held
        skipped = run_once(
            lock_engine=lambda: pg_engine, session_scope=same_session, clock=lambda: NOW
        )
    assert skipped is None
