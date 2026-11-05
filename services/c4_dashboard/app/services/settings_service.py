"""Settings service: defaults, upsert, validation."""

from __future__ import annotations

from datetime import time
from uuid import UUID

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models.orm import HouseServiceSetting
from app.repositories import settings_repo
from app.schemas.settings import ALL_SERVICES, SettingsResponse, SettingsUpsertRequest

DEFAULT_ENABLED: tuple[str, ...] = ALL_SERVICES
DEFAULT_SENSITIVITY = "medium"


def _to_response(row: HouseServiceSetting | None, house_id: UUID) -> SettingsResponse:
    if row is None:
        return SettingsResponse(
            house_id=str(house_id),
            enabled_services=list(DEFAULT_ENABLED),
            quiet_start=None,
            quiet_end=None,
            sensitivity=DEFAULT_SENSITIVITY,
            is_default=True,
            updated_at=None,
        )
    return SettingsResponse(
        house_id=str(row.house_id),
        enabled_services=list(row.enabled_services),
        quiet_start=row.quiet_start.strftime("%H:%M") if row.quiet_start else None,
        quiet_end=row.quiet_end.strftime("%H:%M") if row.quiet_end else None,
        sensitivity=row.sensitivity,
        is_default=False,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


def get_settings(session: Session, house_id: UUID) -> SettingsResponse:
    row = settings_repo.get(session, house_id)
    return _to_response(row, house_id)


def upsert_settings(
    session: Session,
    *,
    house_id: UUID,
    tenant_id: UUID,
    updated_by: UUID,
    payload: SettingsUpsertRequest,
) -> SettingsResponse:
    # Validate service codes (the Literal type already rejects unknowns at the
    # pydantic layer, but double-check defensively).
    unknown = [s for s in payload.enabled_services if s not in ALL_SERVICES]
    if unknown:
        raise ApiError(422, "unknown_service", "unknown service code", {"services": unknown})

    quiet_start = _parse_time(payload.quiet_start)
    quiet_end = _parse_time(payload.quiet_end)

    row = settings_repo.upsert(
        session,
        house_id=house_id,
        tenant_id=tenant_id,
        enabled_services=payload.enabled_services,
        quiet_start=quiet_start,
        quiet_end=quiet_end,
        sensitivity=payload.sensitivity,
        updated_by=updated_by,
    )
    session.commit()
    session.refresh(row)
    return _to_response(row, house_id)


def _parse_time(value: str | None) -> time | None:
    if value is None:
        return None
    hh, mm = value.split(":")
    return time(hour=int(hh), minute=int(mm))
