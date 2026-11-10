"""Dashboard summary endpoint (C4-08)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, Query
from homeai_common.auth import Principal, current_principal

from app.services import stats_aggregator
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=dict)
def dashboard_summary(
    range: Literal["24h", "7d", "30d"] = Query("24h"),
    house_id: str | None = Query(None),
    tenant_id: str | None = Query(None),
    principal: Principal = Depends(current_principal),
    settings: Settings = Depends(get_settings),
    authorization: str | None = Header(default=None),
) -> dict:
    bearer = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
    return stats_aggregator.build_summary(
        settings,
        principal,
        bearer_token=bearer,
        range_key=range,
        house_id=house_id,
        tenant_id=tenant_id,
    )
