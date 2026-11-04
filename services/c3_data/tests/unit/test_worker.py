"""C3-06: worker helpers and the claim/retry flow with fake repos (no TF/Mongo/S3)."""

from __future__ import annotations

from app import worker as worker_mod


def test_worker_id_is_hostname_pid():
    wid = worker_mod.worker_id()
    host, _, pid = wid.rpartition("-")
    assert host
    assert pid.isdigit()
