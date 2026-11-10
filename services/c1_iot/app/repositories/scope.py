"""Tenant/house scoping applied to every repository query (AGENTS.md: tenant isolation).

C1 plan §4.3: iot_staff see their own tenant, cloud_staff every tenant (or the ``tenant_id`` they
ask for), house owners only the houses in their token, service tokens any tenant. A row outside
the caller's scope is reported as 404, never 403, so its existence does not leak.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeai_common.auth import Principal
from sqlalchemy import Select, false


@dataclass(frozen=True)
class Scope:
    """Which rows a caller may see.

    ``tenant_id=None`` means every tenant. ``house_ids=None`` means no house restriction; an empty
    tuple means *no houses* (an owner with no houses sees nothing).
    """

    tenant_id: str | None = None
    house_ids: tuple[str, ...] | None = None

    @classmethod
    def everything(cls) -> Scope:
        return cls()

    @classmethod
    def for_principal(cls, principal: Principal, tenant_id: str | None = None) -> Scope:
        """``tenant_id`` is the optional filter cloud staff and services may pass."""
        if principal.is_service or principal.is_cloud_staff():
            return cls(tenant_id=tenant_id)
        if principal.role == "house_owner":
            return cls(tenant_id=principal.tenant_id, house_ids=tuple(principal.house_ids))
        return cls(tenant_id=principal.tenant_id)

    def apply(self, stmt: Select, model: Any) -> Select:
        """Filter ``stmt`` on ``model.tenant_id`` / ``model.house_id``."""
        if self.tenant_id is not None:
            stmt = stmt.where(model.tenant_id == self.tenant_id)
        if self.house_ids is not None:
            stmt = stmt.where(model.house_id.in_(self.house_ids) if self.house_ids else false())
        return stmt

    def allows(self, tenant_id: str, house_id: str) -> bool:
        if self.tenant_id is not None and tenant_id != self.tenant_id:
            return False
        return self.house_ids is None or house_id in self.house_ids

    def mongo_filter(self) -> dict[str, Any]:
        """The same restriction for ``media_events`` documents."""
        query: dict[str, Any] = {}
        if self.tenant_id is not None:
            query["tenant_id"] = self.tenant_id
        if self.house_ids is not None:
            query["house_id"] = {"$in": list(self.house_ids)}
        return query
