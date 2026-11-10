"""``integrity_reports`` writer (Postgres, schema c3; C3-12, docs §3.2).

A report row records one run of the integrity check for a tenant scope. The
``ux_one_running`` partial unique index (``scope->>'tenant_id'`` where ``status='running'``)
is the safety net against two concurrent checks for the same tenant: ``start`` catches the
``IntegrityError`` and the caller turns it into ``409 check_running``.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.orm import IntegrityReport


class CheckAlreadyRunning(Exception):
    """A running check already exists for this tenant scope (ux_one_running)."""


class IntegrityRepo:
    def __init__(self, session: Session):
        self.session = session

    def start(self, scope: dict[str, Any], requested_by: str | None) -> str:
        """Insert a ``running`` report and return its id.

        Raises :class:`CheckAlreadyRunning` if the partial unique index rejects a second
        running row for the same ``scope.tenant_id``. A ``None`` tenant (cloud_staff all-tenant
        run) is treated the same way by the index (SQL NULL is distinct, so two all-tenant runs
        are allowed; that is acceptable — the demo and scheduler run one at a time).
        """
        report_id = str(_uuid.uuid4())
        self.session.add(
            IntegrityReport(
                report_id=report_id,
                requested_by=requested_by,
                scope=scope,
                status="running",
            )
        )
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise CheckAlreadyRunning() from exc
        return report_id

    def finish(self, report_id: str, findings: list[dict[str, Any]]) -> None:
        report = self.session.get(IntegrityReport, report_id)
        if report is None:
            return
        report.findings = findings
        report.status = "done"
        report.finished_at = datetime.now(UTC)
        self.session.flush()

    def fail(self, report_id: str) -> None:
        report = self.session.get(IntegrityReport, report_id)
        if report is None:
            return
        report.status = "failed"
        report.finished_at = datetime.now(UTC)
        self.session.flush()

    def get(self, report_id: str) -> IntegrityReport | None:
        return self.session.get(IntegrityReport, report_id)

    def list_recent(self, tenant_id: str | None, limit: int = 20) -> list[IntegrityReport]:
        stmt = select(IntegrityReport)
        if tenant_id is not None:
            stmt = stmt.where(IntegrityReport.scope["tenant_id"].astext == tenant_id)
        stmt = stmt.order_by(IntegrityReport.started_at.desc()).limit(limit)
        return list(self.session.execute(stmt).scalars())

    def count_running(self, tenant_id: str | None) -> int:
        stmt = (
            select(func.count())
            .select_from(IntegrityReport)
            .where(IntegrityReport.status == "running")
        )
        if tenant_id is not None:
            stmt = stmt.where(IntegrityReport.scope["tenant_id"].astext == tenant_id)
        return int(self.session.execute(stmt).scalar_one())
