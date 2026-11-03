"""Alerts: list, stats, evaluate (C3), detail and lifecycle actions (static paths first)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from homeai_common.auth import Principal, require_roles, require_scope
from homeai_common.errors import ErrorEnvelope
from homeai_common.pagination import Envelope, Page, PageParams, data_response, page_response
from sqlalchemy.orm import Session

from app.api.deps import (
    alert_reader,
    get_clock,
    get_detection_reader,
    get_house_reader,
    get_session,
    get_settings_reader,
)
from app.constants import ALERT_STATUSES
from app.gateways.types import (
    DependencyUnavailableError,
    DetectionReader,
    HouseReader,
    SettingsReader,
)
from app.repositories.alert_repo import AlertRepository
from app.repositories.rule_repo import RuleRepository
from app.schemas.alert import (
    AlertDetail,
    AlertSummary,
    FalsePositiveBody,
    NoteBody,
    Severity,
    StatBucket,
)
from app.schemas.common import UuidStr
from app.schemas.evaluate import EvaluateRequest, EvaluateResult
from app.services.access_policy import alert_scope
from app.services.alert_service import AlertService
from app.services.evaluate_service import evaluate_detection
from app.services.lifecycle import AlertLifecycleService
from app.services.rule_engine import RuleEngine
from app.services.rule_service import invalid

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])

owner_or_staff = require_roles("house_owner", "cloud_staff")

READ_ERRORS = {
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}
ACTION_ERRORS = {
    **READ_ERRORS,
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope, "description": "invalid_state {from, to}"},
}


def _service(
    session: Session = Depends(get_session),
    houses: HouseReader = Depends(get_house_reader),
    detections: DetectionReader | None = Depends(get_detection_reader),
) -> AlertService:
    return AlertService(session, houses, detections)


def _utc(value: datetime | None) -> datetime | None:
    """Naive query times are UTC (contracts §1); aware ones are converted."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _statuses(csv: str | None) -> list[str] | None:
    if not csv:
        return None
    values = [v.strip() for v in csv.split(",") if v.strip()]
    unknown = [v for v in values if v not in ALERT_STATUSES]
    if unknown:
        raise invalid("status", f"unknown status {unknown[0]!r}; use {', '.join(ALERT_STATUSES)}")
    return values


@router.get(
    "",
    response_model=Page[AlertSummary],
    responses=READ_ERRORS,
    summary="List alerts, newest first",
)
def list_alerts(
    params: PageParams = Depends(),
    status: str | None = Query(None, description="Comma-separated, e.g. open,acknowledged"),
    severity: Severity | None = Query(None),
    alert_type_code: str | None = Query(None),
    house_id: UuidStr | None = Query(None),
    tenant_id: UuidStr | None = Query(None, description="Cloud staff / services only"),
    from_: datetime | None = Query(None, alias="from", description="Inclusive, ISO-8601 UTC"),
    to: datetime | None = Query(None, description="Exclusive, ISO-8601 UTC"),
    principal: Principal = Depends(alert_reader),
    service: AlertService = Depends(_service),
):
    rows, total = service.list(
        alert_scope(principal, tenant_id),
        statuses=_statuses(status),
        severity=severity,
        alert_type_code=alert_type_code,
        house_id=house_id,
        from_=_utc(from_),
        to=_utc(to),
        offset=params.offset,
        limit=params.limit,
    )
    return page_response(rows, total, params)


@router.get(
    "/stats",
    response_model=Envelope[list[StatBucket]],
    responses=READ_ERRORS,
    summary="Alert counts grouped by severity, alert type, house or UTC day",
)
def alert_stats(
    group_by: Literal["severity", "alert_type", "house", "day"] = Query(...),
    from_: datetime = Query(..., alias="from", description="Inclusive, ISO-8601 UTC"),
    to: datetime = Query(..., description="Exclusive; at most 366 days after from"),
    house_id: UuidStr | None = Query(None),
    status: str | None = Query(None, description="Comma-separated statuses"),
    tenant_id: UuidStr | None = Query(None, description="Cloud staff / services only"),
    principal: Principal = Depends(alert_reader),
    service: AlertService = Depends(_service),
):
    buckets = service.stats(
        alert_scope(principal, tenant_id),
        group_by,
        from_=_utc(from_),
        to=_utc(to),
        house_id=house_id,
        statuses=_statuses(status),
    )
    return data_response(buckets)


@router.post(
    "/evaluate",
    status_code=201,
    response_model=Envelope[EvaluateResult],
    response_model_exclude_none=True,
    responses={
        200: {"description": "duplicate (same detection) or no_alert with a reason"},
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope, "description": "unknown detection, wrong house, bad payload"},
        503: {"model": ErrorEnvelope, "description": "C1/C3/C4 unavailable: retry (2/4/8 s)"},
    },
    summary="Evaluate a C3 detection against the rules (service scope alerts:evaluate)",
)
def evaluate(
    body: EvaluateRequest,
    response: Response,
    _: Principal = Depends(require_scope("alerts:evaluate")),
    session: Session = Depends(get_session),
    houses: HouseReader = Depends(get_house_reader),
    settings_reader: SettingsReader = Depends(get_settings_reader),
    detections: DetectionReader | None = Depends(get_detection_reader),
    clock: Callable[[], datetime] = Depends(get_clock),
):
    if detections is None:
        raise DependencyUnavailableError("c3", "MONGO_URL_C2_READER not set")
    engine = RuleEngine(
        alerts=AlertRepository(session),
        rules=RuleRepository(session),
        detections=detections,
        houses=houses,
        settings=settings_reader,
        clock=clock,
    )
    outcome = evaluate_detection(engine, AlertLifecycleService(session), body)
    if not outcome.created:
        response.status_code = 200
    return data_response(outcome.result)


@router.get(
    "/{alert_id}",
    response_model=Envelope[AlertDetail],
    responses={**READ_ERRORS, 404: {"model": ErrorEnvelope}},
    summary="Alert with evidence, timeline and notifications",
)
def get_alert(
    alert_id: UuidStr,
    principal: Principal = Depends(owner_or_staff),
    service: AlertService = Depends(_service),
):
    return data_response(service.detail(alert_id, principal))


def _act(alert_id: str, action: str, principal: Principal, note: str | None, service: AlertService):
    alert = AlertLifecycleService(service.session).transition(alert_id, action, principal, note)
    return data_response(service.detail_of(alert))


@router.post(
    "/{alert_id}/acknowledge", response_model=Envelope[AlertDetail], responses=ACTION_ERRORS
)
def acknowledge(
    alert_id: UuidStr,
    body: NoteBody | None = None,
    principal: Principal = Depends(owner_or_staff),
    service: AlertService = Depends(_service),
):
    return _act(alert_id, "acknowledge", principal, body.note if body else None, service)


@router.post("/{alert_id}/resolve", response_model=Envelope[AlertDetail], responses=ACTION_ERRORS)
def resolve(
    alert_id: UuidStr,
    body: NoteBody | None = None,
    principal: Principal = Depends(owner_or_staff),
    service: AlertService = Depends(_service),
):
    return _act(alert_id, "resolve", principal, body.note if body else None, service)


@router.post(
    "/{alert_id}/false-positive",
    response_model=Envelope[AlertDetail],
    responses=ACTION_ERRORS,
    summary="Mark a false positive (reason required)",
)
def false_positive(
    alert_id: UuidStr,
    body: FalsePositiveBody,
    principal: Principal = Depends(owner_or_staff),
    service: AlertService = Depends(_service),
):
    return _act(alert_id, "false_positive", principal, body.reason, service)
