"""Success envelopes and list pagination (contracts §1).

* Single object: ``{"data": {...}}`` -> response model ``Envelope[AlertOut]``.
* List: ``{"data": [...], "meta": {"page", "page_size", "total"}}`` -> ``Page[AlertOut]``.

Always declare these as the route's ``response_model``. FastAPI then serialises datetimes
through Pydantic as ``...Z``; a plain dict would come out as ``+00:00`` and break the contract.

    @router.get("/alerts", response_model=Page[AlertOut])
    def list_alerts(params: PageParams = Depends()):
        items, total = repo.list(offset=params.offset, limit=params.limit)
        return page_response(items, total, params)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


class PageParams:
    """FastAPI dependency: ``page`` >= 1, ``page_size`` 1-100 (default 25). Bad values -> 422."""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="1-based page number"),
        page_size: int = Query(
            DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page (1-100)"
        ),
    ):
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int


class Page(BaseModel, Generic[T]):
    data: list[T]
    meta: PageMeta


class Envelope(BaseModel, Generic[T]):
    data: T


def page_response(items: Sequence[Any], total: int, params: PageParams) -> dict[str, Any]:
    """Build the list envelope; pair with ``response_model=Page[...]``."""
    return {
        "data": list(items),
        "meta": {"page": params.page, "page_size": params.page_size, "total": total},
    }


def data_response(item: Any) -> dict[str, Any]:
    """Build the single-object envelope; pair with ``response_model=Envelope[...]``."""
    return {"data": item}
