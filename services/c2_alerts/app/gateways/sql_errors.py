"""Turn database failures on read-only connections into DependencyUnavailableError."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import InterfaceError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.gateways.types import DependencyUnavailableError

T = TypeVar("T")

# Connection lost / server down, or the other component's table is not deployed yet
# (ProgrammingError covers "relation c1.houses does not exist" and missing grants).
UNAVAILABLE = (OperationalError, InterfaceError, ProgrammingError)


def read_or_unavailable(session: Session, source: str, query: Callable[[], T]) -> T:
    try:
        return query()
    except UNAVAILABLE as exc:
        session.rollback()  # leave the reader session usable for the next call
        raise DependencyUnavailableError(source, type(exc.orig).__name__) from exc
