"""Dashboard summary endpoint (C4-08)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from homeai_common.auth import Principal, current_principal

from app.services import stats_aggregator
from app.services.service_token import StatsTokenProvider, get_stats_token_provider
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def _token_provider(settings: Settings = Depends(get_settings)) -> StatsTokenProvider:
    return get_stats_token_provider(settings)


@router.get("/summary", response_model=dict)
def dashboard_summary(
    range: Literal["24h", "7d", "30d"] = Query("24h"),
    house_id: str | None = Query(None),
    tenant_id: str | None = Query(None),
    principal: Principal = Depends(current_principal),
    settings: Settings = Depends(get_settings),
    token_provider: StatsTokenProvider = Depends(_token_provider),
) -> dict:
    # Upstream stats are read with C4's own service token (contracts §2.3, §4.6);
    # build_summary scopes every call to this principal's tenant/houses.
    return stats_aggregator.build_summary(
        settings,
        principal,
        token_provider=token_provider,
        range_key=range,
        house_id=house_id,
        tenant_id=tenant_id,
    )
