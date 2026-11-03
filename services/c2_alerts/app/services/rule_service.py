"""Alert rule management: validation (D2 rule-validation table), versioning, tenant defaults."""

from __future__ import annotations

from dataclasses import dataclass

from homeai_common.errors import ApiError
from sqlalchemy.orm import Session

from app.gateways.types import HouseReader
from app.models.orm import AlertRule, AlertType
from app.repositories.alert_type_repo import AlertTypeRepository
from app.repositories.errors import DuplicateRuleError
from app.repositories.rule_repo import RuleRepository
from app.repositories.scope import Scope
from app.schemas.rule import RuleCreate, RuleOut, RuleUpdate


def invalid(field: str, issue: str) -> ApiError:
    """422 in the same shape FastAPI validation errors use."""
    return ApiError(
        422, "validation_error", "request validation failed", [{"field": field, "issue": issue}]
    )


def not_found() -> ApiError:
    return ApiError(404, "not_found", "alert rule not found")


def duplicate() -> ApiError:
    return ApiError(
        409,
        "duplicate_rule",
        "an enabled rule already exists for this tenant, house, alert type and room",
    )


def rule_out(rule: AlertRule, false_positive_count_30d: int = 0) -> RuleOut:
    t = rule.alert_type
    return RuleOut(
        rule_id=rule.rule_id,
        tenant_id=rule.tenant_id,
        house_id=rule.house_id,
        scope="house" if rule.house_id else "tenant_default",
        alert_type_code=t.code,
        alert_type_name=t.name,
        trigger_labels=list(rule.trigger_labels),
        min_confidence=rule.min_confidence,
        room_id=rule.room_id,
        severity=rule.severity,
        effective_severity=rule.severity or t.default_severity,
        is_enabled=rule.is_enabled,
        version=rule.version,
        false_positive_count_30d=false_positive_count_30d,
        created_by=rule.created_by,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@dataclass
class RuleService:
    session: Session
    houses: HouseReader

    @property
    def rules(self) -> RuleRepository:
        return RuleRepository(self.session)

    @property
    def types(self) -> AlertTypeRepository:
        return AlertTypeRepository(self.session)

    # --- reads ------------------------------------------------------------------------------

    def get(self, rule_id: str) -> AlertRule:
        rule = self.rules.get(rule_id, Scope.everything())
        if rule is None:
            raise not_found()
        return rule

    # --- create -----------------------------------------------------------------------------

    def _alert_type(self, code: str) -> AlertType:
        alert_type = self.types.get_by_code(code)
        if alert_type is None:
            raise invalid("alert_type_code", f"unknown alert type {code!r}")
        return alert_type

    def _check_room(self, room_id: str | None, house_id: str | None) -> None:
        if room_id is None:
            return
        if house_id is None:
            raise invalid("room_id", "a room needs a house_id (tenant-wide rules cover all rooms)")
        room = self.houses.room(room_id)
        if room is None or room.house_id != house_id:
            raise invalid("room_id", "room does not belong to house_id")

    def _tenant_for(self, body: RuleCreate) -> str:
        if body.house_id is None:
            if body.tenant_id is None:
                raise invalid("tenant_id", "required when house_id is not given")
            return body.tenant_id
        house = self.houses.house(body.house_id)
        if house is None:
            raise invalid("house_id", "unknown house")
        if body.tenant_id is not None and body.tenant_id != house.tenant_id:
            raise invalid("tenant_id", "does not match the house's tenant")
        return house.tenant_id

    def create(self, body: RuleCreate, created_by: str) -> AlertRule:
        alert_type = self._alert_type(body.alert_type_code)
        tenant_id = self._tenant_for(body)
        self._check_room(body.room_id, body.house_id)
        rule = AlertRule(
            tenant_id=tenant_id,
            house_id=body.house_id,
            alert_type_id=alert_type.alert_type_id,
            trigger_labels=list(body.trigger_labels),
            min_confidence=(
                body.min_confidence
                if body.min_confidence is not None
                else alert_type.default_min_confidence
            ),
            room_id=body.room_id,
            severity=body.severity,
            is_enabled=body.is_enabled,
            created_by=created_by,
        )
        try:
            self.rules.add(rule)
        except DuplicateRuleError as exc:
            raise duplicate() from exc
        self.session.commit()
        self.session.refresh(rule)
        return rule

    # --- update / delete --------------------------------------------------------------------

    def update(self, rule_id: str, expected_version: int, body: RuleUpdate) -> AlertRule:
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            raise invalid("body", "give at least one field to change")
        for name in ("trigger_labels", "min_confidence", "is_enabled"):
            if name in fields and fields[name] is None:
                raise invalid(name, "cannot be null")

        current = self.get(rule_id)
        if "room_id" in fields:
            self._check_room(fields["room_id"], current.house_id)
        try:
            updated = self.rules.update(rule_id, expected_version, Scope.everything(), **fields)
        except DuplicateRuleError as exc:
            raise duplicate() from exc
        if updated is None:
            # Row exists (checked above), so the version was stale.
            raise ApiError(
                412,
                "version_mismatch",
                "the rule was changed by someone else; reload and retry",
                {"current_version": self.get(rule_id).version},
            )
        self.session.commit()
        return updated

    def delete(self, rule_id: str) -> None:
        if not self.rules.soft_delete(rule_id, Scope.everything()):
            raise not_found()
        self.session.commit()

    # --- tenant defaults --------------------------------------------------------------------

    def create_defaults(self, tenant_id: str, created_by: str) -> int:
        """One enabled tenant-wide rule per alert type that has none; idempotent."""
        created = 0
        for alert_type in self.rules.types_missing_default(tenant_id):
            rule = AlertRule(
                tenant_id=tenant_id,
                alert_type_id=alert_type.alert_type_id,
                trigger_labels=[alert_type.trigger_label],
                min_confidence=alert_type.default_min_confidence,
                created_by=created_by,
            )
            try:
                self.rules.add(rule)
                created += 1
            except DuplicateRuleError:
                continue  # created concurrently by another request
        self.session.commit()
        return created
