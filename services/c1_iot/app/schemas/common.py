"""Shared field types for C1 request/response models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, PlainSerializer

MediaKind = Literal["audio", "video"]
FeedStatus = Literal["provisioned", "active", "inactive", "error"]
Connectivity = Literal["online", "offline", "unknown"]
Sensitivity = Literal["low", "medium", "high"]
RoomType = Literal["bedroom", "kitchen", "living", "bathroom", "entry", "other"]
ClipStatus = Literal["queued", "processing", "analyzed", "failed"]


def _uuid_str(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("must be a UUID") from exc


def _timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("must be an IANA timezone, e.g. America/Los_Angeles") from exc
    return value


def to_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso_z(value: datetime) -> str:
    return to_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


# UUID as a lowercase string (contracts §1: IDs are UUID strings everywhere).
UuidStr = Annotated[str, AfterValidator(_uuid_str)]
Timezone = Annotated[str, AfterValidator(_timezone)]
# Always serialised as UTC with "Z" (contracts §1), whatever timezone the driver returned.
UtcDatetime = Annotated[datetime, PlainSerializer(_iso_z, return_type=str)]
