"""JSON logging, context vars and RequestIdMiddleware."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from homeai_common import logging as hlog
from homeai_common.logging import (
    ContextFilter,
    HomeAiJsonFormatter,
    RequestIdMiddleware,
    configure_logging,
    get_request_id,
    mask_email,
    request_id_from_scope,
    set_log_context,
)


@pytest.fixture
def captured():
    """A JSON handler on the root logger writing into a buffer."""
    configure_logging("c2-alerts", level="INFO")
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(HomeAiJsonFormatter())
    handler.addFilter(ContextFilter())
    root = logging.getLogger()
    root.addHandler(handler)
    yield buffer
    root.removeHandler(handler)


def _lines(buffer: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]


def test_log_line_has_contract_fields_and_nests_extra(captured):
    token = hlog.request_id_var.set("req-1")
    try:
        set_log_context(tenant_id="t1", user_id="u1")
        logging.getLogger("c2").info("decision", extra={"detection_id": "d1", "reason": "x"})
    finally:
        hlog.request_id_var.reset(token)
        hlog.tenant_id_var.set(None)
        hlog.user_id_var.set(None)
    (line,) = _lines(captured)
    assert line["level"] == "INFO"
    assert line["service"] == "c2-alerts"
    assert line["request_id"] == "req-1"
    assert line["tenant_id"] == "t1"
    assert line["user_id"] == "u1"
    assert line["msg"] == "decision"
    assert line["ts"].endswith("Z")
    assert line["extra"] == {"detection_id": "d1", "reason": "x"}


def test_exception_is_logged_under_extra(captured):
    try:
        raise ValueError("bad")
    except ValueError:
        logging.getLogger("c2").exception("failed")
    (line,) = _lines(captured)
    assert "ValueError: bad" in line["extra"]["exc_info"]


def test_line_without_extra_has_no_extra_key(captured):
    logging.getLogger("c2").warning("plain %s", "msg")
    (line,) = _lines(captured)
    assert line["msg"] == "plain msg"
    assert "extra" not in line


def test_configure_logging_silences_uvicorn_access():
    configure_logging("c1-iot")
    assert logging.getLogger("uvicorn.access").disabled
    assert logging.getLogger("uvicorn").propagate


@pytest.mark.parametrize(
    ("email", "masked"),
    [
        ("ruth.smith@example.com", "r***@example.com"),
        ("a@b.co", "a***@b.co"),
        ("not-an-email", "not-an-email"),
        (None, None),
        ("", ""),
    ],
)
def test_mask_email(email, masked):
    assert mask_email(email) == masked


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/echo")
    def echo():
        return {"request_id": get_request_id()}

    return app


def test_request_id_is_echoed():
    r = TestClient(_app()).get("/echo", headers={"X-Request-Id": "abc-123"})
    assert r.headers["X-Request-Id"] == "abc-123"
    assert r.json() == {"request_id": "abc-123"}


def test_request_id_is_generated_when_missing():
    r = TestClient(_app()).get("/echo")
    rid = r.headers["X-Request-Id"]
    assert uuid.UUID(rid).version == 4
    assert r.json() == {"request_id": rid}


@pytest.mark.parametrize("bad", ["x" * 200, "has space", "evilé"])
def test_malformed_request_id_is_replaced(bad):
    r = TestClient(_app()).get("/echo", headers={"X-Request-Id": bad.encode("utf-8")})
    assert r.headers["X-Request-Id"] != bad
    uuid.UUID(r.headers["X-Request-Id"])


def test_context_is_reset_after_request():
    TestClient(_app()).get("/echo", headers={"X-Request-Id": "abc"})
    assert get_request_id() is None


def test_access_log_line_written(captured):
    TestClient(_app()).get("/echo", headers={"X-Request-Id": "acc-1"})
    access = [ln for ln in _lines(captured) if ln["msg"] == "request"]
    assert access, "expected an access log line"
    assert access[-1]["request_id"] == "acc-1"
    assert access[-1]["extra"]["status"] == 200
    assert access[-1]["extra"]["path"] == "/echo"


def test_non_http_scope_passes_through():
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    asyncio.run(RequestIdMiddleware(inner)({"type": "lifespan"}, None, None))
    assert seen == ["lifespan"]


def test_request_id_from_scope_prefers_state():
    assert request_id_from_scope({"state": {"request_id": "s1"}}) == "s1"
    assert request_id_from_scope({}) is None
