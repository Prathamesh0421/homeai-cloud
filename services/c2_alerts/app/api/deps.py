"""FastAPI dependencies shared by C2 routers (tests override these)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from homeai_common import db
from homeai_common.auth import Principal, current_principal
from homeai_common.mongo import get_mongo_db
from sqlalchemy.orm import Session

from app.gateways.c1_house_gateway import C1HouseGateway
from app.gateways.detection_gateway import COLLECTION, MongoDetectionGateway
from app.gateways.types import DependencyUnavailableError, DetectionReader, HouseReader
from app.settings import Settings

# Read/write session as c2_app.
get_session = db.get_session


def get_reader_session() -> Iterator[Session]:
    """Read-only session as c2_reader (c4 settings/contacts, c1 houses/rooms)."""
    try:
        db.get_engine(db.READER)
    except RuntimeError as exc:
        raise DependencyUnavailableError("c2_reader", "DATABASE_READER_URL_C2 not set") from exc
    yield from db.get_reader_session()


def get_house_reader(session: Session = Depends(get_reader_session)) -> HouseReader:
    return C1HouseGateway(session)


def get_app_settings(request: Request) -> Settings:
    """The Settings ``create_app`` was built with (tests pass their own)."""
    return request.app.state.settings


def get_detection_reader(settings: Settings = Depends(get_app_settings)) -> DetectionReader | None:
    """C3 ``ai_detections`` reader, or None when MONGO_URL_C2_READER is not configured."""
    if not settings.mongo_reader_url:
        return None
    return MongoDetectionGateway(get_mongo_db(settings.mongo_reader_url)[COLLECTION])


ALERT_READER_ROLES = frozenset({"house_owner", "cloud_staff"})


def alert_reader(principal: Principal = Depends(current_principal)) -> Principal:
    """Owners and cloud staff, or a service token with ``alerts:read`` (C4 dashboards)."""
    if principal.is_user and principal.role in ALERT_READER_ROLES:
        return principal
    if principal.is_service and principal.has_scope("alerts:read"):
        return principal
    raise HTTPException(
        status_code=403, detail={"code": "forbidden", "message": "not allowed to read alerts"}
    )
