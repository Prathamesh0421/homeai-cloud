"""SQLAlchemy ORM models for schema ``c1``.

Every table defaults to schema ``c1`` through ``Base.metadata``; Alembic compares against it.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

SCHEMA = "c1"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


# Register the tables on Base.metadata (imported last: orm.py imports Base from here).
from app.models import orm  # noqa: E402, F401
from app.models.orm import CameraFeed, FeedConfigVersion, House, Room  # noqa: E402

__all__ = ["SCHEMA", "Base", "CameraFeed", "FeedConfigVersion", "House", "Room"]
