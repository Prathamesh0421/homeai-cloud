"""Tier 2: AlertHandoffClient against a real stub C2 over real HTTP.

Runs a tiny FastAPI app (C4 token endpoint + C2 evaluate endpoint) on a localhost port with
uvicorn in a thread, and drives the real ServiceHttpClient / ServiceTokenProvider against it —
so token refresh and the 2/4/8 s retry-on-503 path are exercised, not mocked. Covers 201 new,
200 duplicate, 503-then-retry, and the pending outcome.
"""

from __future__ import annotations

import socket
import threading
import time
from contextlib import closing

import pytest
import uvicorn
from app.gateways.alert_handoff_client import AlertHandoffClient
from fastapi import FastAPI, Request
from homeai_common.service_client import ServiceHttpClient, ServiceTokenProvider

pytestmark = pytest.mark.integration


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _StubState:
    def __init__(self):
        self.evaluate_calls: list[dict] = []
        self.mode = "new"  # new | duplicate | flaky503
        self.flaky_remaining = 0


def _make_stub(state: _StubState) -> FastAPI:
    app = FastAPI()

    @app.post("/api/v1/auth/service-token")
    def token():
        return {"data": {"token": "stub-token", "expires_in": 900}}

    @app.post("/api/v1/alerts/evaluate")
    async def evaluate(request: Request):
        from fastapi.responses import JSONResponse

        body = await request.json()
        state.evaluate_calls.append(body)
        if state.mode == "flaky503" and state.flaky_remaining > 0:
            state.flaky_remaining -= 1
            return JSONResponse(
                status_code=503, content={"error": {"code": "dependency_unavailable"}}
            )
        if state.mode == "duplicate":
            return JSONResponse(
                status_code=200, content={"data": {"decision": "alert", "duplicate": True}}
            )
        return JSONResponse(
            status_code=201,
            content={"data": {"decision": "alert", "alert_id": "a1", "duplicate": False}},
        )

    return app


@pytest.fixture
def stub_server():
    state = _StubState()
    port = _free_port()
    config = uvicorn.Config(_make_stub(state), host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # Wait for startup.
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "stub server did not start"
    yield f"http://127.0.0.1:{port}", state
    server.should_exit = True
    thread.join(timeout=5)


def _client(base_url: str) -> AlertHandoffClient:
    provider = ServiceTokenProvider(
        c4_base_url=base_url,
        client_id="c3-worker",
        client_secret="dev-c3-secret",
        scopes=["alerts:evaluate"],
    )
    # Short backoff so the retry test is fast.
    http = ServiceHttpClient(base_url=base_url, token_provider=provider, backoff=(0.05, 0.05, 0.05))
    return AlertHandoffClient(http)


def _detection(detection_id="d1"):
    return {
        "_id": detection_id,
        "media_id": "m1",
        "house_id": "h1",
        "room_id": "r1",
        "top_label": "glass_break",
        "top_confidence": 0.78,
        "labels": [{"label": "glass_break", "confidence": 0.78}],
        "detected_at": "2026-11-04T00:00:00Z",
    }


def test_handoff_201_new_is_done(stub_server):
    base, state = stub_server
    state.mode = "new"
    assert _client(base)(_detection()) == "done"
    assert state.evaluate_calls[0]["detection_id"] == "d1"
    assert state.evaluate_calls[0]["top_label"] == "glass_break"


def test_handoff_200_duplicate_is_done(stub_server):
    base, state = stub_server
    state.mode = "duplicate"
    assert _client(base)(_detection()) == "done"


def test_handoff_503_then_success_retries(stub_server):
    base, state = stub_server
    state.mode = "flaky503"
    state.flaky_remaining = 2  # two 503s, then the 3rd attempt (mode still flaky but counter 0)
    state.mode = "flaky503"
    result = _client(base)(_detection())
    assert result == "done"
    assert len(state.evaluate_calls) == 3  # retried twice then succeeded


def test_handoff_persistent_503_is_pending(stub_server):
    base, state = stub_server
    state.mode = "flaky503"
    state.flaky_remaining = 99  # always 503
    assert _client(base)(_detection()) == "pending"
