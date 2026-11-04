"""C2-10: POST /alert-rules/subscriptions/sync (the job itself is tested in tests/unit and db)."""

from __future__ import annotations

import pytest
from app.api.deps import get_jobs
from app.gateways.types import DependencyUnavailableError
from app.jobs.subscription_sync import SyncResult
from app.main import create_app
from fastapi.testclient import TestClient

from tests.factories import HOUSE_A1, OWNER_USER, STAFF_USER, TENANT_A

SYNC = "/api/v1/alert-rules/subscriptions/sync"


class _Jobs:
    def __init__(self, result=SyncResult(topics=2, subscribed=3, pending=1, removed=1)):
        self.result = result
        self.calls: list[str | None] = []

    def sync(self, house_id=None):
        self.calls.append(house_id)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def jobs():
    return _Jobs()


@pytest.fixture
def client(settings, jobs):
    app = create_app(settings, checks={})
    app.dependency_overrides[get_jobs] = lambda: jobs
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def staff(client, auth_header):
    return auth_header(user_id=STAFF_USER, role="cloud_staff", tenant_id=TENANT_A)


def test_sync_all_houses(client, staff, jobs):
    r = client.post(SYNC, headers=staff)
    assert r.status_code == 200
    assert r.json() == {
        "data": {"topics": 2, "subscribed": 3, "pending": 1, "removed": 1, "failed": 0}
    }
    assert jobs.calls == [None]


def test_sync_one_house(client, staff, jobs):
    assert client.post(SYNC, json={"house_id": HOUSE_A1}, headers=staff).status_code == 200
    assert client.post(SYNC, json={}, headers=staff).status_code == 200
    assert jobs.calls == [HOUSE_A1, None]


def test_bad_body(client, staff):
    assert client.post(SYNC, json={"house_id": "nope"}, headers=staff).status_code == 422
    assert client.post(SYNC, json={"house": HOUSE_A1}, headers=staff).status_code == 422


def test_busy_is_409(client, staff, jobs):
    jobs.result = None  # the 5-minute job holds the lock
    r = client.post(SYNC, headers=staff)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "sync_in_progress")


def test_contacts_unavailable_is_503(client, staff, jobs):
    jobs.result = DependencyUnavailableError("c4")
    r = client.post(SYNC, headers=staff)
    assert (r.status_code, r.json()["error"]["details"]) == (503, {"source": "c4"})


def test_cloud_staff_only(client, auth_header, jobs):
    owner = auth_header(
        user_id=OWNER_USER, role="house_owner", tenant_id=TENANT_A, house_ids=[HOUSE_A1]
    )
    assert client.post(SYNC, headers=owner).status_code == 403
    assert client.post(SYNC).status_code == 401
    assert jobs.calls == []


def test_listed_before_the_rule_id_route(client):
    paths = list(client.get("/api/v1/docs/c2/openapi.json").json()["paths"])
    assert paths.index(SYNC) < paths.index("/api/v1/alert-rules/{rule_id}")


def test_app_builds_a_job_runner(settings):
    from app.jobs.runner import JobRunner

    app = create_app(settings, checks={})
    assert isinstance(app.state.jobs, JobRunner)
    assert app.state.jobs.notifier is app.state.notifier
