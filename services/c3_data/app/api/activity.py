"""Activity patterns endpoint (C3-11, docs §3.2). GET /activity-patterns, scoped per role."""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from homeai_common.auth import Principal, current_principal
from homeai_common.errors import ApiError
from homeai_common.pagination import Envelope, data_response
from pymongo.database import Database

from app.api.deps import get_mongo
from app.repositories.activity_repo import COLLECTION, ActivityRepo, band, day_str
from app.services.record_scope import house_in_scope, record_scope

router = APIRouter(prefix="/api/v1/activity-patterns", tags=["activity"])

ACTIVITY_ROLES = frozenset({"house_owner", "cloud_staff"})


def activity_principal(principal: Principal = Depends(current_principal)) -> Principal:
    if principal.is_user and principal.role in ACTIVITY_ROLES:
        return principal
    if principal.is_service and principal.has_scope("records:read"):
        return principal
    raise ApiError(403, "forbidden", "not allowed to read activity patterns")


def _pattern_out(doc: dict) -> dict:
    return {
        "house_id": doc.get("house_id"),
        "room_id": doc.get("room_id"),
        "date": doc.get("date"),
        "hours": doc.get("hours", [0] * 24),
        "baseline_mean": doc.get("baseline_mean"),
        "baseline_std": doc.get("baseline_std"),
        "anomaly_score": doc.get("anomaly_score"),
        "band": band(doc.get("anomaly_score")),
        "last_activity_at": doc.get("last_activity_at"),
    }


def _require_uuid(value: str, field: str) -> None:
    try:
        _uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ApiError(
            422,
            "validation_error",
            "invalid id",
            details=[{"field": field, "issue": "must be a UUID"}],
        ) from exc


@router.get("", response_model=Envelope[list[dict]])
def list_activity(
    house_id: str = Query(..., description="House to read patterns for"),
    room_id: str | None = Query(None),
    date: str | None = Query(None, description="yyyy-mm-dd (UTC); defaults to today"),
    days: int = Query(1, ge=1, le=31, description="Number of trailing days (UTC) if date omitted"),
    principal: Principal = Depends(activity_principal),
    mongo: Database = Depends(get_mongo),
) -> dict:
    # A required UuidStr Query param does not reliably run its validator in this FastAPI
    # version, so validate explicitly: a bad id is 422, not a silent pass.
    _require_uuid(house_id, "house_id")
    if room_id is not None:
        _require_uuid(room_id, "room_id")
    # Scope is the floor: an owner may only read their own houses.
    scope = record_scope(principal, None)
    allowed, _ = house_in_scope(scope, house_id)
    if not allowed:
        return data_response([])  # out of scope -> empty, no disclosure

    repo = ActivityRepo(mongo[COLLECTION])
    now = datetime.now(UTC)
    dates = [date] if date else [day_str(now - timedelta(days=d)) for d in range(days)]

    docs = repo.list_for(house_id, room_id, dates)
    # Keep only buckets within the caller's tenant/house scope (defence in depth for cloud_staff
    # who could pass any house_id; owners are already pinned by house_in_scope above).
    if scope.tenant_id is not None:
        docs = [d for d in docs if d.get("tenant_id") in (None, scope.tenant_id)]
    return data_response([_pattern_out(d) for d in docs])
