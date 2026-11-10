"""C1 feeds stats client (best-effort; degrades when C1 is down)."""

from __future__ import annotations

from typing import Any

import httpx


def fetch_feeds_stats(
    base_url: str,
    *,
    bearer_token: str,
    tenant_id: str | None = None,
    house_id: str | None = None,
    timeout: float = 3.0,
) -> dict[str, Any]:
    params: dict[str, str] = {}
    if tenant_id:
        params["tenant_id"] = tenant_id
    if house_id:
        params["house_id"] = house_id
    resp = httpx.get(
        f"{base_url.rstrip('/')}/api/v1/feeds/stats",
        params=params,
        headers={"Authorization": f"Bearer {bearer_token}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    body = resp.json()
    return body.get("data", body)
