"""C3-01: worker skeleton — worker_id shape and startup log."""

from __future__ import annotations

from app import worker


def test_worker_id_is_hostname_pid():
    wid = worker.worker_id()
    host, _, pid = wid.rpartition("-")
    assert host
    assert pid.isdigit()


def test_main_logs_started_then_stops(monkeypatch):
    # Stop the loop immediately so main() returns without sleeping.
    monkeypatch.setattr(worker, "_stop", True)

    messages: list[str] = []
    monkeypatch.setattr(
        worker.logger, "info", lambda msg, *a, **k: messages.append(msg), raising=True
    )
    # configure_logging would reinstall handlers; keep the test independent of it.
    monkeypatch.setattr(worker, "configure_logging", lambda *a, **k: None)

    worker.main()
    assert any("C3 worker started" in m for m in messages)
