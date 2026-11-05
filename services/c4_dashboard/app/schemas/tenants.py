"""Pydantic models for tenants + users admin (contracts §4)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import Email

Role = Literal["house_owner", "iot_staff", "cloud_staff"]


class TenantCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    timezone: str = Field(min_length=1, max_length=40)


class TenantResponse(BaseModel):
    tenant_id: str
    name: str
    timezone: str
    status: str
    created_at: str


class UserCreateRequest(BaseModel):
    email: Email
    password: str = Field(min_length=10, max_length=128)
    role: Role
    display_name: str | None = Field(default=None, max_length=80)
    house_ids: list[str] = Field(default_factory=list)

    @field_validator("password")
    @classmethod
    def _policy(cls, v: str) -> str:
        if not any(c.isalpha() for c in v):
            raise ValueError("password must contain letters")
        if not any(c.isdigit() for c in v):
            raise ValueError("password must contain digits")
        return v


class UserPatchRequest(BaseModel):
    role: Role | None = None
    house_ids: list[str] | None = None
    is_active: bool | None = None
    unlock: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=128)

    @field_validator("password")
    @classmethod
    def _policy(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not any(c.isalpha() for c in v):
            raise ValueError("password must contain letters")
        if not any(c.isdigit() for c in v):
            raise ValueError("password must contain digits")
        return v


class UserResponse(BaseModel):
    user_id: str
    tenant_id: str
    email: str
    role: str
    display_name: str | None = None
    house_ids: list[str] = Field(default_factory=list)
    is_active: bool = True
    last_login_at: str | None = None
