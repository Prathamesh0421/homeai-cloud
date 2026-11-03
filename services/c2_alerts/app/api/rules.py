"""Alert types and alert rules (cloud staff manage rules; owners may read alert types)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Header, Query, Response, status
from homeai_common.auth import Principal, require_roles
from homeai_common.errors import ErrorEnvelope
from homeai_common.pagination import Envelope, Page, PageParams, data_response, page_response
from sqlalchemy.orm import Session

from app.api.deps import get_house_reader, get_session
from app.gateways.types import HouseReader
from app.repositories.alert_type_repo import AlertTypeRepository
from app.repositories.rule_repo import RuleRepository
from app.repositories.scope import Scope
from app.schemas.common import UuidStr
from app.schemas.rule import (
    AlertTypeOut,
    DefaultsRequest,
    DefaultsResult,
    RuleCreate,
    RuleOut,
    RuleUpdate,
)
from app.services.rule_service import RuleService, invalid, rule_out

router = APIRouter(prefix="/api/v1", tags=["alert rules"])

cloud_staff = require_roles("cloud_staff")
owner_or_staff = require_roles("house_owner", "cloud_staff")

ERRORS = {
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}
# Create/update validate house and room through C1's tables.
C1_DOWN = {503: {"model": ErrorEnvelope, "description": "C1 (houses/rooms) unavailable"}}
_ETAG = re.compile(r'^(?:W/)?"?(\d+)"?$')


def _service(
    session: Session = Depends(get_session), houses: HouseReader = Depends(get_house_reader)
) -> RuleService:
    return RuleService(session, houses)


def _version(if_match: str) -> int:
    match = _ETAG.match(if_match.strip())
    if not match:
        raise invalid("If-Match", 'must be the rule version, e.g. "3"')
    return int(match.group(1))


def _etag(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{version}"'


# --- alert types ----------------------------------------------------------------------------


@router.get(
    "/alert-types",
    response_model=Page[AlertTypeOut],
    tags=["alert types"],
    responses=ERRORS,
    summary="List the alert types with their defaults and service code",
)
def list_alert_types(
    params: PageParams = Depends(),
    _: Principal = Depends(owner_or_staff),
    session: Session = Depends(get_session),
):
    types = AlertTypeRepository(session).list_all()
    page = types[params.offset : params.offset + params.limit]
    return page_response([AlertTypeOut.model_validate(t) for t in page], len(types), params)


# --- rules (static paths before /{rule_id}) -------------------------------------------------


@router.get("/alert-rules", response_model=Page[RuleOut], responses=ERRORS)
def list_rules(
    params: PageParams = Depends(),
    tenant_id: UuidStr | None = Query(None),
    house_id: UuidStr | None = Query(None),
    alert_type_code: str | None = Query(None),
    is_enabled: bool | None = Query(None),
    _: Principal = Depends(cloud_staff),
    session: Session = Depends(get_session),
):
    rows, total = RuleRepository(session).list(
        Scope(tenant_id=tenant_id),
        house_id=house_id,
        alert_type_code=alert_type_code,
        is_enabled=is_enabled,
        offset=params.offset,
        limit=params.limit,
    )
    return page_response([rule_out(rule, fp) for rule, fp in rows], total, params)


@router.post(
    "/alert-rules/defaults",
    response_model=Envelope[DefaultsResult],
    responses=ERRORS,
    summary="Create the missing tenant-wide default rules (one per alert type)",
)
def create_defaults(
    body: DefaultsRequest,
    principal: Principal = Depends(cloud_staff),
    service: RuleService = Depends(_service),
):
    return data_response({"created": service.create_defaults(body.tenant_id, principal.sub)})


@router.post(
    "/alert-rules",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[RuleOut],
    responses={**ERRORS, **C1_DOWN, 409: {"model": ErrorEnvelope, "description": "duplicate_rule"}},
)
def create_rule(
    body: RuleCreate,
    response: Response,
    principal: Principal = Depends(cloud_staff),
    service: RuleService = Depends(_service),
):
    rule = service.create(body, created_by=principal.sub)
    response.headers["Location"] = f"/api/v1/alert-rules/{rule.rule_id}"
    _etag(response, rule.version)
    return data_response(rule_out(rule))


@router.get(
    "/alert-rules/{rule_id}",
    response_model=Envelope[RuleOut],
    responses={**ERRORS, 404: {"model": ErrorEnvelope}},
)
def get_rule(
    rule_id: UuidStr,
    response: Response,
    _: Principal = Depends(cloud_staff),
    service: RuleService = Depends(_service),
):
    rule = service.get(rule_id)
    _etag(response, rule.version)
    return data_response(rule_out(rule, service.rules.false_positive_count_30d(rule_id)))


@router.put(
    "/alert-rules/{rule_id}",
    response_model=Envelope[RuleOut],
    responses={
        **ERRORS,
        **C1_DOWN,
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope, "description": "duplicate_rule"},
        412: {"model": ErrorEnvelope, "description": "version_mismatch"},
    },
)
def update_rule(
    rule_id: UuidStr,
    body: RuleUpdate,
    response: Response,
    if_match: str = Header(..., alias="If-Match", description='Rule version, e.g. "3"'),
    _: Principal = Depends(cloud_staff),
    service: RuleService = Depends(_service),
):
    rule = service.update(rule_id, _version(if_match), body)
    _etag(response, rule.version)
    return data_response(rule_out(rule, service.rules.false_positive_count_30d(rule_id)))


@router.delete(
    "/alert-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**ERRORS, 404: {"model": ErrorEnvelope}},
)
def delete_rule(
    rule_id: UuidStr,
    _: Principal = Depends(cloud_staff),
    service: RuleService = Depends(_service),
) -> Response:
    service.delete(rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
