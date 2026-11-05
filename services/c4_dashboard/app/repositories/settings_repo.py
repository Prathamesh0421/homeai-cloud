"""Repository for house service settings."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.orm import HouseServiceSetting


def get(session: Session, house_id: UUID) -> HouseServiceSetting | None:
    return session.get(HouseServiceSetting, house_id)


def upsert(
    session: Session,
    *,
    house_id: UUID,
    tenant_id: UUID,
    enabled_services: list[str],
    quiet_start,
    quiet_end,
    sensitivity: str,
    updated_by: UUID,
) -> HouseServiceSetting:
    row = session.get(HouseServiceSetting, house_id)
    if row is None:
        row = HouseServiceSetting(
            house_id=house_id,
            tenant_id=tenant_id,
            enabled_services=list(enabled_services),
            quiet_start=quiet_start,
            quiet_end=quiet_end,
            sensitivity=sensitivity,
            updated_by=updated_by,
        )
        session.add(row)
    else:
        row.enabled_services = list(enabled_services)
        row.quiet_start = quiet_start
        row.quiet_end = quiet_end
        row.sensitivity = sensitivity
        row.updated_by = updated_by
    return row
