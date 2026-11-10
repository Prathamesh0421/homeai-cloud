"""Integrity-check endpoints (C3-12, docs §3.2, §4.8).

``POST /integrity-checks`` starts a check for the caller's tenant scope and returns ``202
{report_id}``; the scan runs in the background and the report moves ``running -> done``. A
second concurrent run for the same tenant is ``409 check_running`` (the ``ux_one_running``
partial unique index is the real guard). ``GET /integrity-reports[/{id}]`` reads the list or
one report with its findings. cloud_staff only: integrity is an operator tool.
"""

from __future__ import annotations

import logging
import uuid as _uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from homeai_common import db, mongo
from homeai_common.auth import Principal, require_roles
from homeai_common.errors import ApiError
from homeai_common.pagination import Envelope, data_response
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.repositories.integrity_repo import CheckAlreadyRunning, IntegrityRepo
from app.services import integrity_service
from app.services.record_scope import record_scope
from app.settings import Settings

logger = logging.getLogger("c3.integrity")

router = APIRouter(prefix="/api/v1", tags=["integrity"])

cloud = require_roles("cloud_staff")


def _report_out(report) -> dict:
    return {
        "report_id": report.report_id,
        "scope": report.scope,
        "status": report.status,
        "findings": report.findings,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
    }


def _run_scan(report_id: str, tenant_id: str | None, mongo_url: str) -> None:
    """Background task: scan Mongo and record findings on an already-running report.

    Self-contained (its own session + Mongo handle) because the request's session is closed by
    the time this runs. Both the baseline job and this use the same pattern as the scheduler.
    """
    mongo_db = mongo.get_mongo_db(mongo_url)
    try:
        findings = integrity_service.run_checks(mongo_db, tenant_id)
        with db.session_scope() as session:
            IntegrityRepo(session).finish(report_id, findings)
    except Exception:
        logger.exception("integrity scan failed", extra={"report_id": report_id})
        with db.session_scope() as session:
            IntegrityRepo(session).fail(report_id)


@router.post(
    "/integrity-checks",
    response_model=Envelope[dict],
    status_code=202,
    dependencies=[Depends(cloud)],
)
def run_check(
    request: Request,
    background: BackgroundTasks,
    tenant_id: str | None = Query(None, description="Narrow the check to one tenant (UUID)"),
    principal: Principal = Depends(require_roles("cloud_staff")),
    session: Session = Depends(get_session),
) -> dict:
    """Start the integrity scan (202). 409 if a check is already running for this tenant."""
    if tenant_id is not None:
        _require_uuid(tenant_id, "tenant_id")

    settings: Settings = request.app.state.settings
    if not settings.mongo_url:
        raise ApiError(503, "dependency_unavailable", "mongo not configured")

    # cloud_staff: all tenants unless a tenant_id narrows it (scope is the floor; a cloud_staff
    # caller legitimately sees every tenant for an operator audit).
    scope = record_scope(principal, tenant_id)

    repo = IntegrityRepo(session)
    try:
        report_id = repo.start({"tenant_id": scope.tenant_id}, principal.sub)
    except CheckAlreadyRunning as exc:
        raise ApiError(409, "check_running", "an integrity check is already running") from exc
    session.commit()  # make the running row visible before the scan starts

    background.add_task(_run_scan, report_id, scope.tenant_id, settings.mongo_url)
    return data_response({"report_id": report_id, "status": "running"})


@router.get(
    "/integrity-reports/{report_id}", response_model=Envelope[dict], dependencies=[Depends(cloud)]
)
def get_report(report_id: str, session: Session = Depends(get_session)) -> dict:
    _require_uuid(report_id, "report_id")
    report = IntegrityRepo(session).get(report_id)
    if report is None:
        raise ApiError(404, "not_found", "integrity report not found")
    return data_response(_report_out(report))


@router.get(
    "/integrity-reports", response_model=Envelope[list[dict]], dependencies=[Depends(cloud)]
)
def list_reports(
    tenant_id: str | None = Query(None),
    session: Session = Depends(get_session),
) -> dict:
    if tenant_id is not None:
        _require_uuid(tenant_id, "tenant_id")
    reports = IntegrityRepo(session).list_recent(tenant_id)
    return data_response([_report_out(r) for r in reports])


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
