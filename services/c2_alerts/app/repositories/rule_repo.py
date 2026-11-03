"""Alert rules: CRUD with optimistic versioning, soft delete, and the rule set for evaluation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import case, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.constants import SEVERITY_RANK
from app.models.orm import Alert, AlertRule, AlertType
from app.repositories.errors import DuplicateRuleError, violated_constraint
from app.repositories.scope import Scope

DUPLICATE_INDEX = "ux_rules_dup"
FALSE_POSITIVE_WINDOW = timedelta(days=30)
EDITABLE_FIELDS = frozenset(
    {"trigger_labels", "min_confidence", "room_id", "severity", "is_enabled"}
)


def _severity_rank(rule: Any, alert_type: Any) -> Any:
    """SQL expression: rank of the rule's effective severity (rule override or type default)."""
    effective = func.coalesce(rule.severity, alert_type.default_severity)
    return case(SEVERITY_RANK, value=effective, else_=0)


def _false_positive_count_30d() -> Any:
    return (
        select(func.count())
        .where(
            Alert.rule_id == AlertRule.rule_id,
            Alert.status == "false_positive",
            Alert.triggered_at >= func.now() - FALSE_POSITIVE_WINDOW,
        )
        .correlate(AlertRule)
        .scalar_subquery()
    )


class RuleRepository:
    def __init__(self, session: Session):
        self.session = session

    def _flush_or_duplicate(self, work: Any) -> Any:
        # Savepoint so a duplicate does not poison the caller's transaction.
        try:
            with self.session.begin_nested():
                return work()
        except IntegrityError as exc:
            if violated_constraint(exc) == DUPLICATE_INDEX:
                raise DuplicateRuleError from exc
            raise

    def add(self, rule: AlertRule) -> AlertRule:
        def work() -> AlertRule:
            self.session.add(rule)
            self.session.flush()
            return rule

        return self._flush_or_duplicate(work)

    def get(self, rule_id: str, scope: Scope) -> AlertRule | None:
        stmt = select(AlertRule).where(AlertRule.rule_id == rule_id, AlertRule.deleted_at.is_(None))
        return self.session.scalars(scope.apply(stmt, AlertRule)).first()

    def list(
        self,
        scope: Scope,
        *,
        house_id: str | None = None,
        alert_type_code: str | None = None,
        is_enabled: bool | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[tuple[AlertRule, int]], int]:
        """Rules (not deleted) with their false-positive count over the last 30 days."""
        base = scope.apply(
            select(AlertRule.rule_id).where(AlertRule.deleted_at.is_(None)), AlertRule
        )
        if house_id is not None:
            base = base.where(AlertRule.house_id == house_id)
        if is_enabled is not None:
            base = base.where(AlertRule.is_enabled.is_(is_enabled))
        if alert_type_code is not None:
            base = base.join(AlertType).where(AlertType.code == alert_type_code)
        ids = base.subquery()

        total = self.session.scalar(select(func.count()).select_from(ids)) or 0
        stmt = (
            select(AlertRule, _false_positive_count_30d())
            .where(AlertRule.rule_id.in_(select(ids.c.rule_id)))
            .order_by(AlertRule.created_at.desc(), AlertRule.rule_id)
            .offset(offset)
            .limit(limit)
        )
        rows = [(rule, int(fp)) for rule, fp in self.session.execute(stmt).unique()]
        return rows, total

    def update(
        self, rule_id: str, expected_version: int, scope: Scope, **fields: Any
    ) -> AlertRule | None:
        """Apply ``fields`` if the rule is still at ``expected_version``; bump version.

        Returns ``None`` when no row matched (unknown, deleted, out of scope or stale version);
        the caller tells 404 from 412 with ``get()``.
        """
        unknown = set(fields) - EDITABLE_FIELDS
        if unknown:
            raise ValueError(f"not editable: {sorted(unknown)}")
        stmt = (
            update(AlertRule)
            .where(
                AlertRule.rule_id == rule_id,
                AlertRule.version == expected_version,
                AlertRule.deleted_at.is_(None),
            )
            .values(**fields, version=AlertRule.version + 1, updated_at=func.now())
            .returning(AlertRule.rule_id)
            .execution_options(synchronize_session=False)
        )
        if scope.tenant_id is not None:
            stmt = stmt.where(AlertRule.tenant_id == scope.tenant_id)

        updated_id = self._flush_or_duplicate(lambda: self.session.scalar(stmt))
        if updated_id is None:
            return None
        rule = self.session.get(AlertRule, updated_id)
        self.session.refresh(rule)
        return rule

    def soft_delete(self, rule_id: str, scope: Scope) -> bool:
        stmt = (
            update(AlertRule)
            .where(AlertRule.rule_id == rule_id, AlertRule.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now(), version=AlertRule.version + 1)
            .execution_options(synchronize_session=False)
        )
        if scope.tenant_id is not None:
            stmt = stmt.where(AlertRule.tenant_id == scope.tenant_id)
        return self.session.execute(stmt).rowcount == 1

    def enabled_for(self, tenant_id: str, house_id: str) -> list[AlertRule]:
        """Rules the engine evaluates for a house, strongest first.

        House rules, plus tenant defaults (``house_id IS NULL``) for alert types that have no
        enabled house rule. Order: effective severity desc, room-specific before room-less,
        oldest first, then rule_id for a stable tiebreak.
        """
        house_rule = aliased(AlertRule)
        active = (AlertRule.is_enabled.is_(True), AlertRule.deleted_at.is_(None))
        has_house_rule = exists().where(
            house_rule.tenant_id == tenant_id,
            house_rule.house_id == house_id,
            house_rule.alert_type_id == AlertRule.alert_type_id,
            house_rule.is_enabled.is_(True),
            house_rule.deleted_at.is_(None),
        )
        stmt = (
            select(AlertRule)
            .join(AlertType, AlertType.alert_type_id == AlertRule.alert_type_id)
            .where(AlertRule.tenant_id == tenant_id, *active)
            .where(
                (AlertRule.house_id == house_id) | (AlertRule.house_id.is_(None) & ~has_house_rule)
            )
            .order_by(
                _severity_rank(AlertRule, AlertType).desc(),
                AlertRule.room_id.is_(None),
                AlertRule.created_at,
                AlertRule.rule_id,
            )
        )
        return list(self.session.scalars(stmt).unique())

    def types_missing_default(self, tenant_id: str) -> list[AlertType]:
        """Alert types with no enabled tenant-wide default rule (for POST /alert-rules/defaults)."""
        has_default = exists().where(
            AlertRule.tenant_id == tenant_id,
            AlertRule.house_id.is_(None),
            AlertRule.room_id.is_(None),
            AlertRule.alert_type_id == AlertType.alert_type_id,
            AlertRule.is_enabled.is_(True),
            AlertRule.deleted_at.is_(None),
        )
        stmt = select(AlertType).where(~has_default).order_by(AlertType.alert_type_id)
        return list(self.session.scalars(stmt))
