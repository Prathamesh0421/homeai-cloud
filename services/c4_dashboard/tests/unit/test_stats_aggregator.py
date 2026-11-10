"""Unit tests for live dashboard summary merge + degrade."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

from app.services import stats_aggregator


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
    monkeypatch.setattr(stats_aggregator.c3_client, "fetch_detections_stats", boom)

    principal = FakePrincipal(role="cloud_staff", tenant_id=None, house_ids=())
    out = stats_aggregator.build_summary(
        settings,
        principal,  # type: ignore[arg-type]
        bearer_token="tok",
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
    monkeypatch.setattr(
        stats_aggregator.c3_client,
        "fetch_detections_stats",
        lambda *a, **k: ([{"key": "speech", "count": 10}], 42),
    )

    principal = FakePrincipal(role="cloud_staff", tenant_id=None, house_ids=())
    out = stats_aggregator.build_summary(
        settings,
        principal,  # type: ignore[arg-type]
        bearer_token="tok",
        range_key="7d",
    )
    assert out["data"]["kpis"]["feeds_online"] == 3
    assert out["data"]["kpis"]["alerts"] == 3
    assert out["data"]["kpis"]["open_alerts"] == 1
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
            bearer_token="tok",
            house_id="h2",
        )
        raise AssertionError("expected ApiError")
    except stats_aggregator.ApiError as exc:
        assert exc.status_code == 403
