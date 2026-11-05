"""Records browsing API (C3-10, docs §3.2, §4.6). Static paths before parameterised ones."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from homeai_common.auth import Principal, current_principal
from homeai_common.errors import ApiError
from homeai_common.pagination import Envelope, Page, PageParams, data_response, page_response
from pymongo.database import Database

from app.api.deps import get_mongo, get_reader_connection, get_records_limiter
from app.schemas.records import Record
from app.services.rate_limit import SlidingWindowLimiter
from app.services.record_query import RecordQuery
from app.services.record_scope import record_scope

router = APIRouter(prefix="/api/v1/records", tags=["records"])

RECORD_ROLES = frozenset({"house_owner", "iot_staff", "cloud_staff"})


def records_principal(principal: Principal = Depends(current_principal)) -> Principal:
    """Users in a record-browsing role, or a service with records:read."""
    if principal.is_user and principal.role in RECORD_ROLES:
        return principal
    if principal.is_service and principal.has_scope("records:read"):
        return principal
    raise ApiError(403, "forbidden", "not allowed to browse records")


def _rate_limit(principal: Principal, limiter: SlidingWindowLimiter) -> None:
    key = principal.sub or "anon"
    retry = limiter.hit(key)
    if retry:
        raise ApiError(
            429,
            "rate_limited",
            "too many requests; try again shortly",
            details={"retry_after": retry},
            headers={"Retry-After": str(retry)},
        )


def _parse_filter(filter_: str | None) -> dict[str, str]:
    """``filter=field:value`` (repeatable as comma-separated field:value pairs)."""
    out: dict[str, str] = {}
    if not filter_:
        return out
    for part in filter_.split(","):
        if ":" not in part:
            raise ApiError(422, "validation_error", f"bad filter '{part}'; use field:value")
        field, value = part.split(":", 1)
        out[field.strip()] = value.strip()
    return out


@router.get("/{entity}", response_model=Page[Record])
def list_records(
    entity: str,
    request: Request,
    params: PageParams = Depends(),
    house_id: str | None = Query(None),
    tenant_id: str | None = Query(None, description="Cloud staff / services only"),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    filter_: str | None = Query(None, alias="filter"),
    principal: Principal = Depends(records_principal),
    reader_conn=Depends(get_reader_connection),
    mongo: Database = Depends(get_mongo),
    limiter: SlidingWindowLimiter = Depends(get_records_limiter),
) -> dict:
    _rate_limit(principal, limiter)
    scope = record_scope(principal, tenant_id)
    q = RecordQuery(reader_conn, mongo)
    rows, total = q.list(
        entity,
        scope,
        house_id=house_id,
        from_=from_,
        to=to,
        filters=_parse_filter(filter_),
        offset=params.offset,
        limit=params.limit,
        principal_is_iot=principal.is_user and principal.role == "iot_staff",
    )
    return page_response(rows, total, params)


@router.get("/{entity}/{record_id}", response_model=Envelope[Record])
def get_record(
    entity: str,
    record_id: str,
    request: Request,
    principal: Principal = Depends(records_principal),
    reader_conn=Depends(get_reader_connection),
    mongo: Database = Depends(get_mongo),
    limiter: SlidingWindowLimiter = Depends(get_records_limiter),
) -> dict:
    _rate_limit(principal, limiter)
    if entity == "alerts" and principal.is_user and principal.role == "iot_staff":
        raise ApiError(403, "forbidden", "iot staff may not read alerts")
    scope = record_scope(principal, None)
    q = RecordQuery(reader_conn, mongo)
    record = q.get(entity, record_id, scope)
    if record is None:
        raise ApiError(404, "not_found", "record not found")
    if "_id" in record:
        record["id"] = str(record.pop("_id"))
    return data_response(record)
