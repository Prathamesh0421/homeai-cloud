"""SQLAlchemy ORM models for schema ``c3`` (tables arrive in C3-02).

Every table defaults to schema ``c3`` through ``Base.metadata``; Alembic compares against it.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

SCHEMA = "c3"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


# Register the tables on Base.metadata (imported last: orm.py imports Base from here).
from app.models import orm  # noqa: E402, F401
