"""FastAPI dependencies shared by C2 routers (tests override these)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends
from homeai_common import db
from sqlalchemy.orm import Session

from app.gateways.c1_house_gateway import C1HouseGateway
from app.gateways.types import DependencyUnavailableError, HouseReader

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
