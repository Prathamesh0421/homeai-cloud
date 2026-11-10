"""C3-12 (Tier 2): integrity_reports on real Postgres.

The ``ux_one_running`` partial unique index (one running check per tenant) is a Postgres-only
guarantee — SQLite ignores partial/expression indexes — so the 409 path must be proven here.
"""

from __future__ import annotations

import pytest
from app.repositories.integrity_repo import CheckAlreadyRunning, IntegrityRepo
from sqlalchemy import text

pytestmark = pytest.mark.integration

TENANT = "11111111-0000-0000-0000-00000000c112"


def _cleanup(pg_session):
    pg_session.execute(
        text("DELETE FROM c3.integrity_reports WHERE scope->>'tenant_id' = :t"),
        {"t": TENANT},
    )
    pg_session.execute(text("DELETE FROM c3.integrity_reports WHERE scope->>'tenant_id' IS NULL"))
    pg_session.commit()


def test_second_running_check_same_tenant_is_rejected(pg_session):
    _cleanup(pg_session)
    repo = IntegrityRepo(pg_session)
    try:
        repo.start({"tenant_id": TENANT}, requested_by=None)
        pg_session.commit()

        with pytest.raises(CheckAlreadyRunning):
            repo.start({"tenant_id": TENANT}, requested_by=None)
    finally:
        _cleanup(pg_session)


def test_finishing_a_check_frees_the_tenant(pg_session):
    _cleanup(pg_session)
    repo = IntegrityRepo(pg_session)
    try:
        rid = repo.start({"tenant_id": TENANT}, requested_by=None)
        pg_session.commit()
        repo.finish(rid, [{"kind": "orphan_detection", "severity": "medium"}])
        pg_session.commit()

        report = repo.get(rid)
        assert report.status == "done"
        assert report.finished_at is not None
        assert report.findings[0]["kind"] == "orphan_detection"

        # With the first done, a new running check for the same tenant is allowed.
        rid2 = repo.start({"tenant_id": TENANT}, requested_by=None)
        pg_session.commit()
        assert rid2 != rid
    finally:
        _cleanup(pg_session)


def test_failing_a_check_sets_failed_status(pg_session):
    _cleanup(pg_session)
    repo = IntegrityRepo(pg_session)
    try:
        rid = repo.start({"tenant_id": TENANT}, requested_by=None)
        pg_session.commit()
        repo.fail(rid)
        pg_session.commit()
        assert repo.get(rid).status == "failed"
    finally:
        _cleanup(pg_session)


def test_count_running(pg_session):
    _cleanup(pg_session)
    repo = IntegrityRepo(pg_session)
    try:
        assert repo.count_running(TENANT) == 0
        repo.start({"tenant_id": TENANT}, requested_by=None)
        pg_session.commit()
        assert repo.count_running(TENANT) == 1
    finally:
        _cleanup(pg_session)
