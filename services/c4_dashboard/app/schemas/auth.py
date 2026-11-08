"""Auth request/response schemas (contracts §2 and §4.7)."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

# The project's seed/demo users use `.test` addresses (RFC 2606 reserved TLD),
# which pydantic's EmailStr rejects. We accept any RFC-5321-ish local@domain
# form here; the DB lookup is what actually authorises a login.
Email = Annotated[
    str,
    StringConstraints(
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        min_length=3,
        max_length=254,
    ),
]


class LoginRequest(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    token: str
    expires_in: int
    landing: str
    claims: dict[str, Any]


class ServiceTokenRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=40)
    client_secret: str = Field(min_length=1, max_length=128)
    scope: list[str] = Field(default_factory=list)


class ServiceTokenResponse(BaseModel):
    token: str
    expires_in: int


class UserPublic(BaseModel):
    user_id: str
    tenant_id: str | None = None
    email: str
    role: str
    display_name: str | None = None
    house_ids: list[str] = Field(default_factory=list)
    is_active: bool = True
    last_login_at: str | None = None


class HouseRef(BaseModel):
    house_id: str
    name: str | None = None


class AuthMeResponse(BaseModel):
    user: UserPublic
    houses: list[HouseRef] = Field(default_factory=list)


class RevokedListResponse(BaseModel):
    jti: list[str] = Field(default_factory=list)


class JwksResponse(BaseModel):
    keys: list[dict[str, Any]]


# Contract envelope wrappers: success bodies are {"data": <object>}.
class LoginEnvelope(BaseModel):
    data: LoginResponse


class ServiceTokenEnvelope(BaseModel):
    data: ServiceTokenResponse


class AuthMeEnvelope(BaseModel):
    data: AuthMeResponse


class RevokedListEnvelope(BaseModel):
    data: RevokedListResponse
