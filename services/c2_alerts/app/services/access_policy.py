"""Which alerts a caller may see (tenant isolation; AGENTS.md §3)."""

from __future__ import annotations

from homeai_common.auth import Principal

from app.repositories.scope import Scope


def alert_scope(principal: Principal, tenant_id: str | None = None) -> Scope:
    """Scope for alert reads.

    * house_owner: own tenant and only the houses in the JWT (``tenant_id`` ignored).
    * cloud_staff and services with ``alerts:read`` (C4 dashboards): every tenant, narrowed
      by the ``tenant_id`` the caller passes.
    Routers reject other callers before this is reached.
    """
    if principal.is_user and principal.role == "house_owner":
        return Scope(tenant_id=principal.tenant_id, house_ids=tuple(principal.house_ids))
    return Scope(tenant_id=tenant_id)
