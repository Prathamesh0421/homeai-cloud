"""C3 detection stats client (best-effort)."""

from __future__ import annotations

from typing import Any

import httpx


def fetch_detections_stats(
    base_url: str,
    *,
    bearer_token: str,
    group_by: str,
    from_iso: str | None = None,
    to_iso: str | None = None,
    house_id: str | None = None,
    tenant_id: str | None = None,
    timeout: float = 3.0,
) -> tuple[list[dict[str, Any]], int]:
    params: dict[str, str] = {"group_by": group_by}
    if from_iso:
        params["from"] = from_iso
    if to_iso:
        params["to"] = to_iso
    if house_id:
        params["house_id"] = house_id
    if tenant_id:
        params["tenant_id"] = tenant_id
    resp = httpx.get(
        f"{base_url.rstrip('/')}/api/v1/detections/stats",
        params=params,
        headers={"Authorization": f"Bearer {bearer_token}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    body = resp.json()
    data = body.get("data", body)
    buckets = list(data) if isinstance(data, list) else []
    total_clips = int((body.get("meta") or {}).get("total_clips") or 0)
    return buckets, total_clips
