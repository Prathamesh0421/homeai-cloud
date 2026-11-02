"""SQLAlchemy engine, session, and Base metadata for C4.

Until P0-3 lands `homeai_common.db`, C4 keeps a local engine factory. The
`BASE_METADATA` is what Alembic autogenerate compares against.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


BASE_METADATA = Base.metadata


def make_engine(url: str | None = None) -> Engine:
    url = (
        url
        or os.environ.get("DATABASE_URL_C4")
        or ("postgresql+psycopg://c4_app:devpass@postgres:5432/homeai")
    )
    return create_engine(url, pool_pre_ping=True, future=True)


_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionFactory


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
