"""PageParams bounds, envelope shapes and the Z datetime contract."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from homeai_common.errors import install_error_handlers
from homeai_common.pagination import (
    MAX_PAGE_SIZE,
    Envelope,
    Page,
    PageParams,
    data_response,
    page_response,
)
from pydantic import BaseModel

ROWS = [{"id": str(i), "at": datetime(2026, 10, 31, 14, 32, i, tzinfo=UTC)} for i in range(60)]


class Item(BaseModel):
    id: str
    at: datetime


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/items", response_model=Page[Item])
    def list_items(params: PageParams = Depends()):
        return page_response(ROWS[params.offset : params.offset + params.limit], len(ROWS), params)

    @app.get("/items/one", response_model=Envelope[Item])
    def one():
        return data_response(ROWS[5])

    return TestClient(app)


def test_defaults(client):
    body = client.get("/items").json()
    assert body["meta"] == {"page": 1, "page_size": 25, "total": 60}
    assert len(body["data"]) == 25
    assert body["data"][0]["id"] == "0"


def test_last_partial_page(client):
    body = client.get("/items", params={"page": 3, "page_size": 25}).json()
    assert [d["id"] for d in body["data"]] == [str(i) for i in range(50, 60)]


def test_page_past_end_is_empty_list_not_404(client):
    r = client.get("/items", params={"page": 10})
    assert r.status_code == 200
    assert r.json()["data"] == []


@pytest.mark.parametrize(
    "params", [{"page": 0}, {"page_size": 0}, {"page_size": MAX_PAGE_SIZE + 1}, {"page": "x"}]
)
def test_out_of_range_is_422_validation_error(client, params):
    r = client.get("/items", params=params)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_datetimes_serialise_with_z(client):
    assert client.get("/items").json()["data"][0]["at"] == "2026-10-31T14:32:00Z"
    assert client.get("/items/one").json() == {"data": {"id": "5", "at": "2026-10-31T14:32:05Z"}}


def test_offset_math():
    p = PageParams(page=4, page_size=10)
    assert (p.offset, p.limit) == (30, 10)
