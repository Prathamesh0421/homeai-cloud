"""SQLAlchemy ORM models for schema ``c2`` (tables arrive in C2-02).

Every table defaults to schema ``c2`` through ``Base.metadata``; Alembic compares against it.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

SCHEMA = "c2"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)
