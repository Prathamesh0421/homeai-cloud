"""C2 alerts stats + recent alerts client (best-effort)."""

from __future__ import annotations

from typing import Any

import httpx


def fetch_alerts_stats(
    base_url: str,
    *,
    bearer_token: str,
    group_by: str,
    from_iso: str,
    to_iso: str,
    house_id: str | None = None,
    tenant_id: str | None = None,
    timeout: float = 3.0,
) -> list[dict[str, Any]]:
    params: dict[str, str] = {
        "group_by": group_by,
        "from": from_iso,
        "to": to_iso,
    }
    if house_id:
        params["house_id"] = house_id
    if tenant_id:
        params["tenant_id"] = tenant_id
    resp = httpx.get(
        f"{base_url.rstrip('/')}/api/v1/alerts/stats",
        params=params,
        headers={"Authorization": f"Bearer {bearer_token}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    body = resp.json()
    data = body.get("data", body)
    return list(data) if isinstance(data, list) else []


def fetch_recent_alerts(
    base_url: str,
    *,
    bearer_token: str,
    house_id: str | None = None,
    tenant_id: str | None = None,
    page_size: int = 5,
    timeout: float = 3.0,
) -> list[dict[str, Any]]:
    params: dict[str, str] = {"page": "1", "page_size": str(page_size)}
    if house_id:
        params["house_id"] = house_id
    if tenant_id:
        params["tenant_id"] = tenant_id
    resp = httpx.get(
        f"{base_url.rstrip('/')}/api/v1/alerts",
        params=params,
        headers={"Authorization": f"Bearer {bearer_token}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    body = resp.json()
    data = body.get("data", body)
    return list(data) if isinstance(data, list) else []
