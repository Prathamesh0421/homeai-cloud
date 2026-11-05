"""Pydantic models for house service settings and emergency contacts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.schemas.auth import Email

Sensitivity = Literal["low", "medium", "high"]
ServiceCode = Literal["fire_safety", "distress", "intrusion", "fall", "wellness", "presence", "pet"]
ALL_SERVICES: tuple[str, ...] = (
    "fire_safety",
    "distress",
    "intrusion",
    "fall",
    "wellness",
    "presence",
    "pet",
)
ContactType = Literal["family", "caregiver", "neighbor", "emergency_service"]

TimeStr = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]


class SettingsResponse(BaseModel):
    house_id: str
    enabled_services: list[str]
    quiet_start: str | None = None
    quiet_end: str | None = None
    sensitivity: Sensitivity = "medium"
    is_default: bool = False
    updated_at: str | None = None


class SettingsUpsertRequest(BaseModel):
    enabled_services: list[ServiceCode]
    quiet_start: TimeStr | None = None
    quiet_end: TimeStr | None = None
    sensitivity: Sensitivity = "medium"

    @model_validator(mode="after")
    def _both_or_neither(self) -> SettingsUpsertRequest:
        if (self.quiet_start is None) != (self.quiet_end is None):
            raise ValueError("quiet_start and quiet_end must both be set or both be null")
        return self


class ContactResponse(BaseModel):
    contact_id: str
    house_id: str
    name: str
    email: str
    phone: str | None = None
    contact_type: ContactType
    priority: int


class ContactCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: Email
    phone: str | None = Field(default=None, max_length=20)
    contact_type: ContactType
    priority: int | None = Field(default=None, ge=1, le=5)


class ContactPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    email: Email | None = None
    phone: str | None = Field(default=None, max_length=20)
    contact_type: ContactType | None = None
    priority: int | None = Field(default=None, ge=1, le=5)


class ContactReorderRequest(BaseModel):
    contact_ids: list[str] = Field(min_length=1)
