"""I-5 (docs/05 §4): C4 ``GET /dashboard/summary`` KPIs match upstream stats; C3 down → unavailable.

Gateway only, real tokens. Stopping c3 uses docker compose and is restored afterwards.
"""

from __future__ import annotations

import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import seed_ids

pytestmark = pytest.mark.integration

MAPLE = seed_ids.HOUSES["maple"][0]
OWNER = "owner.maple@acme.test"
OPS = "ops@homeai.test"
ROOT = Path(__file__).resolve().parents[2]


def _compose_base() -> list[str]:
    """``docker compose`` argv prefix; override with ``HOMEAI_COMPOSE`` (space-separated files)."""
    raw = os.environ.get("HOMEAI_COMPOSE")
    if raw:
        files = raw.split()
    else:
        files = ["infra/docker-compose.yml"]
        prod = ROOT / "infra" / "docker-compose.prod.yml"
        if os.environ.get("HOMEAI_USE_PROD_COMPOSE") == "1" and prod.exists():
            files.append(str(prod.relative_to(ROOT)) if prod.is_relative_to(ROOT) else str(prod))
    cmd = ["docker", "compose"]
    for f in files:
        cmd.extend(["-f", f])
    # Profiles used on EC2 / full local stack.
    for profile in ("gateway", "c1", "c3"):
        cmd.extend(["--profile", profile])
    return cmd


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_compose_base(), *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_i5_summary_kpis_match_upstream_stats(stack):
    """Summary KPIs for Maple equal the same window counted via C1/C2/C3 APIs."""
    token = stack.user_token(OWNER)
    now = datetime.now(UTC)
    from_iso, to_iso = _iso(now - timedelta(hours=24)), _iso(now)

    summary = stack.call(
        "GET",
        "/api/v1/dashboard/summary",
        token,
        params={"house_id": MAPLE, "range": "24h"},
    )
    data = summary["data"]
    kpis = data["kpis"]
    assert summary["meta"]["range"] == "24h"
    # Healthy stack: no dependency should be marked down for this assertion.
    assert "c1" not in summary["meta"]["unavailable"]
    assert "c2" not in summary["meta"]["unavailable"]
    assert "c3" not in summary["meta"]["unavailable"]

    # C1 /feeds/stats is staff or scope feeds:read only (C4 reads it with its c4-dashboard
    # service token), so the reference count is taken as cloud staff, narrowed to Maple.
    feeds = stack.call(
        "GET",
        "/api/v1/feeds/stats",
        stack.user_token(OPS),
        params={"tenant_id": seed_ids.tenant_of(MAPLE), "house_id": MAPLE},
    )["data"]
    assert kpis["houses"] == int(feeds.get("houses") or 0)
    assert kpis["feeds_total"] == int(feeds.get("total") or 0)
    assert kpis["feeds_online"] == int(feeds.get("online") or 0)
    by_status = feeds.get("by_status") or {}
    assert kpis["feeds_active"] == int(by_status.get("active") or 0)

    sev = stack.call(
        "GET",
        "/api/v1/alerts/stats",
        token,
        params={"group_by": "severity", "from": from_iso, "to": to_iso, "house_id": MAPLE},
    )["data"]
    sev_map = {str(b["key"]): int(b["count"]) for b in sev}
    assert kpis["alerts"] == sum(sev_map.values())
    for level in ("critical", "high", "medium", "low"):
        assert data["alerts_by_severity"][level] == sev_map.get(level, 0)

    open_page = stack.call(
        "GET",
        "/api/v1/alerts",
        token,
        params={"house_id": MAPLE, "status": "open,acknowledged", "page_size": 1},
    )
    assert kpis["open_alerts"] == int((open_page.get("meta") or {}).get("total") or 0)

    det = stack.call(
        "GET",
        "/api/v1/detections/stats",
        token,
        params={"group_by": "top_label", "from": from_iso, "to": to_iso, "house_id": MAPLE},
    )
    assert kpis["clips_classified"] == int((det.get("meta") or {}).get("total_clips") or 0)


def test_i5_summary_marks_c3_unavailable_when_stopped(stack):
    """Stopping c3-data → ``meta.unavailable`` contains ``c3``; other KPIs still present."""
    token = stack.user_token(OPS)
    # Warm path while healthy.
    healthy = stack.call("GET", "/api/v1/dashboard/summary", token, params={"range": "24h"})
    assert "c3" not in healthy["meta"]["unavailable"]

    stopped = False
    try:
        result = _compose("stop", "c3-data", check=False)
        if result.returncode != 0:
            pytest.skip(
                "could not stop c3-data "
                f"(exit {result.returncode}): {(result.stderr or result.stdout)[:300]}"
            )
        stopped = True

        # Aggregator times out (~3 s) then marks the source; allow a few retries.
        unavailable: list[str] = []
        body: dict = {}
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            body = stack.call("GET", "/api/v1/dashboard/summary", token, params={"range": "24h"})
            unavailable = body["meta"]["unavailable"]
            if "c3" in unavailable:
                break
            time.sleep(2)
        assert "c3" in unavailable, body
        assert "kpis" in body["data"]
        assert isinstance(body["data"]["kpis"]["clips_classified"], int)
    finally:
        if stopped:
            _compose("start", "c3-data", check=False)
            # Wait until C3 answers again so later tests are not flaky.
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                try:
                    again = stack.call(
                        "GET", "/api/v1/dashboard/summary", token, params={"range": "24h"}
                    )
                    if "c3" not in again["meta"]["unavailable"]:
                        break
                except Exception:
                    pass
                time.sleep(3)
