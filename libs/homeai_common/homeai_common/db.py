"""SQLAlchemy 2.x (sync) engine and sessions.

Each service connects as its own ``cX_app`` role, plus optionally a read-only ``cX_reader``
role for documented cross-component reads (contracts §5.1). Configure once at startup::

    configure_db(settings.database_url, reader_url=settings.database_reader_url)

then use ``Depends(get_session)`` / ``Depends(get_reader_session)`` in routers and
``with session_scope():`` in jobs.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

CONNECT_TIMEOUT_SECONDS = 3

_engines: dict[str, Engine] = {}
_factories: dict[str, sessionmaker[Session]] = {}

PRIMARY = "primary"
READER = "reader"


def make_engine(url: str, **kwargs: Any) -> Engine:
    """Engine with pre-ping and a short connect timeout (so health checks never hang)."""
    options: dict[str, Any] = {"pool_pre_ping": True}
    if make_url(url).get_backend_name() == "postgresql":
        options["connect_args"] = {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
    options.update(kwargs)
    return create_engine(url, **options)


def configure_db(url: str, *, reader_url: str | None = None, **engine_kwargs: Any) -> None:
    """Create the process-wide engines. Call once from ``create_app()`` / worker start."""
    dispose_db()
    _register(PRIMARY, make_engine(url, **engine_kwargs))
    if reader_url:
        _register(READER, make_engine(reader_url, **engine_kwargs))


def _register(name: str, engine: Engine) -> None:
    _engines[name] = engine
    _factories[name] = sessionmaker(bind=engine, expire_on_commit=False)


def dispose_db() -> None:
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()
    _factories.clear()


def get_engine(name: str = PRIMARY) -> Engine:
    if name not in _engines:
        raise RuntimeError(f"database {name!r} not configured; call configure_db() at startup")
    return _engines[name]


def _factory(name: str) -> sessionmaker[Session]:
    get_engine(name)
    return _factories[name]


@contextmanager
def session_scope(name: str = PRIMARY) -> Iterator[Session]:
    """Commit on success, roll back on error, always close."""
    session = _factory(name)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency for the service's own (read/write) database role.

    The handler or service commits explicitly; anything uncommitted is rolled back on close.
    """
    session = _factory(PRIMARY)()
    try:
        yield session
    finally:
        session.close()


def get_reader_session() -> Iterator[Session]:
    """FastAPI dependency for the read-only ``cX_reader`` role."""
    session = _factory(READER)()
    try:
        yield session
    finally:
        session.close()


def check_database(name: str = PRIMARY) -> None:
    """Health check: raises if ``SELECT 1`` fails."""
    with get_engine(name).connect() as conn:
        conn.execute(text("SELECT 1"))
