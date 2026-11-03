"""Tenant/house scoping applied to every repository query (AGENTS.md: tenant isolation)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, false


@dataclass(frozen=True)
class Scope:
    """Which rows a caller may see.

    ``tenant_id=None`` means every tenant (cloud staff). ``house_ids=None`` means no house
    restriction; an empty tuple means *no houses* (an owner with no houses sees nothing).
    """

    tenant_id: str | None = None
    house_ids: tuple[str, ...] | None = None

    @classmethod
    def everything(cls) -> Scope:
        return cls()

    def apply(self, stmt: Select, model: Any) -> Select:
        if self.tenant_id is not None:
            stmt = stmt.where(model.tenant_id == self.tenant_id)
        if self.house_ids is not None:
            stmt = stmt.where(model.house_id.in_(self.house_ids) if self.house_ids else false())
        return stmt
