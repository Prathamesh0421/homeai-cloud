"""Live dashboard summary from C1/C2/C3 (C4-08).

Rollup from ``dashboard_stats_daily`` is deferred (C4-09). This path is live-only
for the requested range window. Failed upstreams return zeros and are listed in
``meta.unavailable``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

from homeai_common.auth import Principal

from app.errors import ApiError
from app.gateways import c1_client, c2_client, c3_client
from app.settings import Settings

logger = logging.getLogger(__name__)

RANGE_HOURS = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}


def _range_bounds(range_key: str) -> tuple[datetime, datetime]:
    hours = RANGE_HOURS.get(range_key)
    if hours is None:
        raise ApiError(422, "invalid_range", "range must be 24h, 7d, or 30d")
    now = datetime.now(UTC)
    return now - timedelta(hours=hours), now


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _buckets_to_map(buckets: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for b in buckets:
        key = str(b.get("key", ""))
        out[key] = int(b.get("count") or 0)
    return out


def _safe(name: str, fn: Callable[[], Any], default: Any) -> tuple[Any, str | None]:
    try:
        return fn(), None
    except Exception as exc:
        logger.warning("dashboard upstream %s failed: %s", name, exc)
        return default, name


def build_summary(
    settings: Settings,
    principal: Principal,
    *,
    bearer_token: str,
    range_key: str = "24h",
    house_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    from_dt, to_dt = _range_bounds(range_key)
    from_iso, to_iso = _iso(from_dt), _iso(to_dt)

    scoped_house = house_id
    scoped_tenant = tenant_id
    if principal.is_user and principal.role == "house_owner":
        allowed = set(principal.house_ids or ())
        if house_id and house_id not in allowed:
            raise ApiError(403, "forbidden", "house not in your scope")
        if not house_id:
            if len(allowed) == 1:
                scoped_house = next(iter(allowed))
            elif not allowed:
                raise ApiError(422, "house_required", "no houses on account")
            else:
                raise ApiError(
                    422, "house_required", "house_id is required when you own multiple houses"
                )
        scoped_tenant = principal.tenant_id
    elif principal.is_user and principal.role == "iot_staff":
        scoped_tenant = principal.tenant_id
    elif principal.is_user and principal.role == "cloud_staff":
        pass
    else:
        raise ApiError(403, "forbidden", "role cannot read dashboard summary")

    cs_tenant = scoped_tenant if principal.role == "cloud_staff" else None

    with ThreadPoolExecutor(max_workers=5) as pool:
        f_feeds = pool.submit(
            _safe,
            "c1",
            lambda: c1_client.fetch_feeds_stats(
                settings.c1_base_url,
                bearer_token=bearer_token,
                tenant_id=scoped_tenant,
                house_id=scoped_house,
            ),
            {},
        )
        f_sev = pool.submit(
            _safe,
            "c2",
            lambda: c2_client.fetch_alerts_stats(
                settings.c2_base_url,
                bearer_token=bearer_token,
                group_by="severity",
                from_iso=from_iso,
                to_iso=to_iso,
                house_id=scoped_house,
                tenant_id=cs_tenant,
            ),
            [],
        )
        f_day = pool.submit(
            _safe,
            "c2",
            lambda: c2_client.fetch_alerts_stats(
                settings.c2_base_url,
                bearer_token=bearer_token,
                group_by="day",
                from_iso=from_iso,
                to_iso=to_iso,
                house_id=scoped_house,
                tenant_id=cs_tenant,
            ),
            [],
        )
        f_recent = pool.submit(
            _safe,
            "c2",
            lambda: c2_client.fetch_recent_alerts(
                settings.c2_base_url,
                bearer_token=bearer_token,
                house_id=scoped_house,
                tenant_id=cs_tenant,
            ),
            [],
        )
        f_det = pool.submit(
            _safe,
            "c3",
            lambda: c3_client.fetch_detections_stats(
                settings.c3_base_url,
                bearer_token=bearer_token,
                group_by="top_label",
                from_iso=from_iso,
                to_iso=to_iso,
                house_id=scoped_house,
                tenant_id=cs_tenant,
            ),
            ([], 0),
        )

        feeds, err_c1 = f_feeds.result()
        severity_buckets, err_sev = f_sev.result()
        day_buckets, err_day = f_day.result()
        recent, err_recent = f_recent.result()
        det, err_c3 = f_det.result()

    unavailable = [e for e in (err_c1, err_sev, err_day, err_recent, err_c3) if e]
    # Deduplicate while preserving order.
    seen: set[str] = set()
    uniq_unavailable: list[str] = []
    for u in unavailable:
        if u not in seen:
            seen.add(u)
            uniq_unavailable.append(u)

    if isinstance(det, tuple):
        detection_buckets, total_clips = det
    else:
        detection_buckets, total_clips = [], 0

    sev_map = _buckets_to_map(severity_buckets or [])
    alerts_total = sum(sev_map.values())
    by_status = (feeds or {}).get("by_status") or {}
    feeds_active = int(by_status.get("active") or 0)
    feeds_total = int((feeds or {}).get("total") or 0)
    feeds_online = int((feeds or {}).get("online") or 0)
    houses = int((feeds or {}).get("houses") or (1 if scoped_house else 0))

    open_alerts = sum(
        1
        for a in (recent or [])
        if str(a.get("status", "")).lower() in {"open", "acknowledged", "new", "active"}
    )

    detections_top = [
        {"label": str(b.get("key")), "count": int(b.get("count") or 0)}
        for b in sorted(
            detection_buckets or [], key=lambda x: int(x.get("count") or 0), reverse=True
        )[:8]
    ]

    alerts_by_day = [
        {"date": str(b.get("key")), "count": int(b.get("count") or 0)}
        for b in sorted(day_buckets or [], key=lambda x: str(x.get("key")))
    ]

    recent_alerts = [
        {
            "alert_id": a.get("alert_id"),
            "alert_type_code": a.get("alert_type_code"),
            "severity": a.get("severity"),
            "status": a.get("status"),
            "house_name": a.get("house_name") or a.get("house_id"),
            "room_name": a.get("room_name"),
            "triggered_at": a.get("triggered_at"),
        }
        for a in (recent or [])[:5]
    ]

    data = {
        "kpis": {
            "houses": houses,
            "feeds_total": feeds_total,
            "feeds_active": feeds_active,
            "feeds_online": feeds_online,
            "alerts": alerts_total,
            "open_alerts": open_alerts,
            "clips_classified": total_clips,
        },
        "alerts_by_severity": {
            "critical": sev_map.get("critical", 0),
            "high": sev_map.get("high", 0),
            "medium": sev_map.get("medium", 0),
            "low": sev_map.get("low", 0),
        },
        "alerts_by_day": alerts_by_day,
        "detections_top": detections_top,
        "recent_alerts": recent_alerts,
        "activity": [],
    }
    meta = {
        "range": range_key,
        "generated_at": _iso(datetime.now(UTC)),
        "live_since": from_iso,
        "unavailable": uniq_unavailable,
    }
    return {"data": data, "meta": meta}
