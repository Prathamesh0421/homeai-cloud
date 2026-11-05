"""Role/tenant scoping for the Records API (C3-10, docs §4.6; AGENTS.md tenant isolation).

Mirrors C2's Scope but adds the iot_staff branch C3's entities need:
  house_owner -> own tenant, only the houses in the JWT
  iot_staff   -> own tenant, all its houses
  cloud_staff -> all tenants, narrowed by an optional tenant_id query param

Scope.apply turns that into SQL/Mongo filters. ``house_ids=()`` (owner with no houses) matches
nothing, so a list just comes back empty (contracts: empty results are 200, never 403/404).
"""

from __future__ import annotations

from dataclasses import dataclass

from homeai_common.auth import Principal
from homeai_common.errors import ApiError


@dataclass(frozen=True)
class RecordScope:
    tenant_id: str | None = None
    house_ids: tuple[str, ...] | None = None

    def mongo_filter(self) -> dict:
        """Build a Mongo query fragment for tenant/house scope."""
        flt: dict = {}
        if self.tenant_id is not None:
            flt["tenant_id"] = self.tenant_id
        if self.house_ids is not None:
            # Empty tuple -> an impossible match so the caller sees nothing.
            flt["house_id"] = {"$in": list(self.house_ids)} if self.house_ids else {"$in": []}
        return flt


def record_scope(principal: Principal, tenant_id: str | None = None) -> RecordScope:
    """Resolve the caller's scope for record reads."""
    if principal.is_user and principal.role == "house_owner":
        return RecordScope(
            tenant_id=principal.tenant_id, house_ids=tuple(principal.house_ids or ())
        )
    if principal.is_user and principal.role == "iot_staff":
        return RecordScope(tenant_id=principal.tenant_id)
    if principal.is_user and principal.role == "cloud_staff":
        return RecordScope(tenant_id=tenant_id)
    # Services with records:read behave like cloud_staff (narrowed by tenant_id).
    if principal.is_service:
        return RecordScope(tenant_id=tenant_id)
    raise ApiError(403, "forbidden", "not allowed to browse records")
