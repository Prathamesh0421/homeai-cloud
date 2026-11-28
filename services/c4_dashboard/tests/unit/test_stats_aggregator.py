"""Unit tests for live dashboard summary merge + degrade."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import httpx
import pytest
from app.services import stats_aggregator


class FakeTokens:
    """Stands in for StatsTokenProvider."""

    def __init__(self, token: str = "svc-tok", error: Exception | None = None):
        self._token = token
        self._error = error
        self.invalidated = 0

    def token(self) -> str:
        if self._error:
            raise self._error
        return self._token

    def invalidate(self) -> None:
        self.invalidated += 1


@dataclass
class FakePrincipal:
    role: str
    tenant_id: str | None
    house_ids: tuple[str, ...]
    kind: str = "user"

    @property
    def is_user(self) -> bool:
        return self.kind == "user"


def test_summary_marks_unavailable_when_upstreams_fail(monkeypatch):
    settings = MagicMock()
    settings.c1_base_url = "http://c1"
    settings.c2_base_url = "http://c2"
    settings.c3_base_url = "http://c3"

    def boom(*_a, **_k):
        raise RuntimeError("down")

    monkeypatch.setattr(stats_aggregator.c1_client, "fetch_feeds_stats", boom)
    monkeypatch.setattr(stats_aggregator.c2_client, "fetch_alerts_stats", boom)
    monkeypatch.setattr(stats_aggregator.c2_client, "fetch_recent_alerts", boom)
    monkeypatch.setattr(stats_aggregator.c2_client, "fetch_open_alert_count", boom)
    monkeypatch.setattr(stats_aggregator.c3_client, "fetch_detections_stats", boom)

    principal = FakePrincipal(role="cloud_staff", tenant_id=None, house_ids=())
    out = stats_aggregator.build_summary(
        settings,
        principal,  # type: ignore[arg-type]
        token_provider=FakeTokens(),
        range_key="24h",
    )
    assert out["data"]["kpis"]["alerts"] == 0
    assert out["data"]["kpis"]["feeds_total"] == 0
    assert set(out["meta"]["unavailable"]) == {"c1", "c2", "c3"}


def test_summary_merges_live_buckets(monkeypatch):
    settings = MagicMock()
    settings.c1_base_url = "http://c1"
    settings.c2_base_url = "http://c2"
    settings.c3_base_url = "http://c3"

    monkeypatch.setattr(
        stats_aggregator.c1_client,
        "fetch_feeds_stats",
        lambda *a, **k: {
            "houses": 2,
            "total": 4,
            "online": 3,
            "by_status": {"active": 3},
        },
    )

    def alerts_stats(*_a, **k):
        if k.get("group_by") == "severity":
            return [{"key": "critical", "count": 2}, {"key": "low", "count": 1}]
        return [{"key": "2026-11-09", "count": 3}]

    monkeypatch.setattr(stats_aggregator.c2_client, "fetch_alerts_stats", alerts_stats)
    monkeypatch.setattr(
        stats_aggregator.c2_client,
        "fetch_recent_alerts",
        lambda *a, **k: [
            {
                "alert_id": "a1",
                "alert_type_code": "smoke",
                "severity": "critical",
                "status": "open",
                "house_id": "h1",
                "triggered_at": "2026-11-09T12:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(stats_aggregator.c2_client, "fetch_open_alert_count", lambda *a, **k: 7)
    monkeypatch.setattr(
        stats_aggregator.c3_client,
        "fetch_detections_stats",
        lambda *a, **k: ([{"key": "speech", "count": 10}], 42),
    )

    principal = FakePrincipal(role="cloud_staff", tenant_id=None, house_ids=())
    out = stats_aggregator.build_summary(
        settings,
        principal,  # type: ignore[arg-type]
        token_provider=FakeTokens(),
        range_key="7d",
    )
    assert out["data"]["kpis"]["feeds_online"] == 3
    assert out["data"]["kpis"]["alerts"] == 3
    assert out["data"]["kpis"]["open_alerts"] == 7
    assert out["data"]["kpis"]["clips_classified"] == 42
    assert out["data"]["alerts_by_severity"]["critical"] == 2
    assert out["data"]["detections_top"][0]["label"] == "speech"
    assert out["meta"]["unavailable"] == []
    assert out["meta"]["range"] == "7d"


def test_owner_forbidden_other_house():
    settings = MagicMock()
    principal = FakePrincipal(role="house_owner", tenant_id="t1", house_ids=("h1",))
    try:
        stats_aggregator.build_summary(
            settings,
            principal,  # type: ignore[arg-type]
            token_provider=FakeTokens(),
            house_id="h2",
        )
        raise AssertionError("expected ApiError")
    except stats_aggregator.ApiError as exc:
        assert exc.status_code == 403


def _settings():
    settings = MagicMock()
    settings.c1_base_url = "http://c1"
    settings.c2_base_url = "http://c2"
    settings.c3_base_url = "http://c3"
    return settings


def _record_calls(monkeypatch) -> list[tuple[str, dict]]:
    """Patch every upstream gateway; return the (name, kwargs) of each call."""
    calls: list[tuple[str, dict]] = []

    def rec(name, result):
        def fn(*_a, **k):
            calls.append((name, k))
            return result

        return fn

    monkeypatch.setattr(
        stats_aggregator.c1_client, "fetch_feeds_stats", rec("c1.feeds_stats", {"total": 1})
    )
    monkeypatch.setattr(
        stats_aggregator.c2_client, "fetch_alerts_stats", rec("c2.alerts_stats", [])
    )
    monkeypatch.setattr(
        stats_aggregator.c2_client, "fetch_recent_alerts", rec("c2.recent_alerts", [])
    )
    monkeypatch.setattr(
        stats_aggregator.c2_client, "fetch_open_alert_count", rec("c2.open_count", 0)
    )
    monkeypatch.setattr(
        stats_aggregator.c3_client, "fetch_detections_stats", rec("c3.detections", ([], 0))
    )
    return calls


def test_owner_summary_uses_service_token_scoped_to_owner_house(monkeypatch):
    """I-5 regression: C1 /feeds/stats rejects owner tokens, so C4 must use its own token."""
    calls = _record_calls(monkeypatch)
    principal = FakePrincipal(role="house_owner", tenant_id="t1", house_ids=("h1",))
    out = stats_aggregator.build_summary(
        _settings(),
        principal,  # type: ignore[arg-type]
        token_provider=FakeTokens("svc-tok"),
    )
    assert out["meta"]["unavailable"] == []
    assert len(calls) == 6
    for name, kwargs in calls:
        assert kwargs["bearer_token"] == "svc-tok", name
        # The service token sees all tenants upstream, so every call must be fenced.
        assert kwargs["tenant_id"] == "t1", name
        assert kwargs["house_id"] == "h1", name


def test_iot_staff_summary_scoped_to_own_tenant(monkeypatch):
    calls = _record_calls(monkeypatch)
    principal = FakePrincipal(role="iot_staff", tenant_id="t1", house_ids=())
    out = stats_aggregator.build_summary(
        _settings(),
        principal,  # type: ignore[arg-type]
        token_provider=FakeTokens(),
        tenant_id="t-other",  # ignored for iot_staff
    )
    assert out["meta"]["unavailable"] == []
    assert {k["tenant_id"] for _, k in calls} == {"t1"}


def test_cloud_staff_tenant_filter_passed_to_every_upstream(monkeypatch):
    calls = _record_calls(monkeypatch)
    principal = FakePrincipal(role="cloud_staff", tenant_id=None, house_ids=())
    stats_aggregator.build_summary(
        _settings(),
        principal,  # type: ignore[arg-type]
        token_provider=FakeTokens(),
        tenant_id="t2",
    )
    assert {k["tenant_id"] for _, k in calls} == {"t2"}


@pytest.mark.parametrize("role", ["house_owner", "iot_staff"])
def test_tenant_roles_without_tenant_are_rejected(monkeypatch, role):
    calls = _record_calls(monkeypatch)
    principal = FakePrincipal(role=role, tenant_id=None, house_ids=("h1",))
    with pytest.raises(stats_aggregator.ApiError) as exc:
        stats_aggregator.build_summary(
            _settings(),
            principal,  # type: ignore[arg-type]
            token_provider=FakeTokens(),
        )
    assert exc.value.status_code == 403
    assert calls == []


def test_service_principal_rejected(monkeypatch):
    _record_calls(monkeypatch)
    principal = FakePrincipal(role="", tenant_id=None, house_ids=(), kind="service")
    with pytest.raises(stats_aggregator.ApiError) as exc:
        stats_aggregator.build_summary(
            _settings(),
            principal,  # type: ignore[arg-type]
            token_provider=FakeTokens(),
        )
    assert exc.value.status_code == 403


def test_token_failure_marks_all_upstreams_unavailable(monkeypatch):
    calls = _record_calls(monkeypatch)
    principal = FakePrincipal(role="cloud_staff", tenant_id=None, house_ids=())
    out = stats_aggregator.build_summary(
        _settings(),
        principal,  # type: ignore[arg-type]
        token_provider=FakeTokens(error=RuntimeError("no secret")),
    )
    assert calls == []
    assert out["meta"]["unavailable"] == ["c1", "c2", "c3"]
    assert out["data"]["kpis"]["feeds_total"] == 0


def test_upstream_401_invalidates_cached_token(monkeypatch):
    _record_calls(monkeypatch)
    request = httpx.Request("GET", "http://c1/api/v1/feeds/stats")

    def unauthorized(*_a, **_k):
        raise httpx.HTTPStatusError(
            "401", request=request, response=httpx.Response(401, request=request)
        )

    monkeypatch.setattr(stats_aggregator.c1_client, "fetch_feeds_stats", unauthorized)
    tokens = FakeTokens()
    principal = FakePrincipal(role="cloud_staff", tenant_id=None, house_ids=())
    out = stats_aggregator.build_summary(
        _settings(),
        principal,  # type: ignore[arg-type]
        token_provider=tokens,
    )
    assert out["meta"]["unavailable"] == ["c1"]
    assert tokens.invalidated == 1
