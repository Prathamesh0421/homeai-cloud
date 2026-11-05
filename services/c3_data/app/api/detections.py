"""Detection statistics endpoint (C3-10, contract §4.6)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from homeai_common.auth import Principal, current_principal
from homeai_common.errors import ApiError
from pymongo.database import Database

from app.api.deps import get_mongo
from app.schemas.records import StatBucket
from app.services.detection_stats import detection_stats
from app.services.record_scope import record_scope

router = APIRouter(prefix="/api/v1/detections", tags=["detections"])

STATS_ROLES = frozenset({"house_owner", "cloud_staff"})


def stats_principal(principal: Principal = Depends(current_principal)) -> Principal:
    if principal.is_user and principal.role in STATS_ROLES:
        return principal
    if principal.is_service and principal.has_scope("records:read"):
        return principal
    raise ApiError(403, "forbidden", "not allowed to read detection stats")


@router.get("/stats")
def stats(
    group_by: Literal["top_label", "day", "house"] = Query(...),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    house_id: str | None = Query(None),
    tenant_id: str | None = Query(None, description="Cloud staff / services only"),
    principal: Principal = Depends(stats_principal),
    mongo: Database = Depends(get_mongo),
) -> dict:
    scope = record_scope(principal, tenant_id)
    buckets, total_clips = detection_stats(
        mongo, scope, group_by, from_=from_, to=to, house_id=house_id
    )
    # Contract §4.6: data is the bucket list, meta carries total_clips.
    return {
        "data": [StatBucket(key=b["key"], count=b["count"]).model_dump() for b in buckets],
        "meta": {"total_clips": total_clips},
    }
