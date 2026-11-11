"""C2-11: C1 playback URLs with C2's service token (app/gateways/c1_clip_client.py).

C1 and C4 are an ``httpx.MockTransport``; the clock is a counter, so caching is exact.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.gateways.c1_clip_client import (
    FAILURE_TTL_S,
    REUSE_MARGIN_S,
    SCOPE,
    C1ClipClient,
    make_clip_client,
)

START = datetime(2026, 11, 10, 20, 0, tzinfo=UTC)
MEDIA = "77777777-0000-4000-8000-000000000001"
OTHER = "77777777-0000-4000-8000-000000000002"


class FakeC1C4:
    """C4's service-token endpoint and C1's playback-url endpoint, with a call log."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.token_status = 200
        self.clip_status: dict[str, int] = {}
        self.clip_error: Exception | None = None
        self.body_override: str | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if request.url.path == "/api/v1/auth/service-token":
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": {"code": "unauthorized"}})
            return httpx.Response(200, json={"data": {"token": "svc-token", "expires_in": 900}})
        if self.clip_error:
            raise self.clip_error
        media_id = request.url.path.split("/")[-2]
        status = self.clip_status.get(media_id, 200)
        if status != 200:
            return httpx.Response(status, json={"error": {"code": "x"}})
        if self.body_override is not None:
            return httpx.Response(200, text=self.body_override)
        expires = (START + timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
        return httpx.Response(
            200,
            json={"data": {"url": f"https://s3.example/{media_id}.wav?sig", "expires_at": expires}},
        )

    def paths(self) -> list[str]:
        return [r.url.path for r in self.calls]


@pytest.fixture
def fake():
    return FakeC1C4()


@pytest.fixture
def clock():
    return {"now": START.timestamp()}


@pytest.fixture
def client(fake, clock):
    return C1ClipClient(
        c1_base_url="http://c1-iot:8001/",
        c4_base_url="http://c4-dashboard:8004",
        client_id="c2-alerts",
        client_secret="dev-c2-secret",
        http=httpx.Client(transport=httpx.MockTransport(fake)),
        clock=lambda: clock["now"],
    )


def test_gets_a_service_token_then_the_playback_url(client, fake):
    assert client.playback_url(MEDIA) == f"https://s3.example/{MEDIA}.wav?sig"
    token_req, clip_req = fake.calls
    assert str(token_req.url) == "http://c4-dashboard:8004/api/v1/auth/service-token"
    assert json.loads(token_req.content) == {
        "client_id": "c2-alerts",
        "client_secret": "dev-c2-secret",
        "scope": [SCOPE],
    }
    assert str(clip_req.url) == f"http://c1-iot:8001/api/v1/clips/{MEDIA}/playback-url"
    assert clip_req.headers["Authorization"] == "Bearer svc-token"


def test_a_url_is_reused_until_shortly_before_it_expires(client, fake, clock):
    first = client.playback_url(MEDIA)
    clock["now"] += 15 * 60 - REUSE_MARGIN_S - 1  # still inside the reuse window
    assert client.playback_url(MEDIA) == first
    assert fake.paths().count(f"/api/v1/clips/{MEDIA}/playback-url") == 1
    clock["now"] += 2  # 3 minutes before C1's expiry: ask C1 again
    client.playback_url(MEDIA)
    assert fake.paths().count(f"/api/v1/clips/{MEDIA}/playback-url") == 2


def test_the_token_is_shared_by_clips_and_refreshed_at_80_percent(client, fake, clock):
    client.playback_url(MEDIA)
    client.playback_url(OTHER)
    assert fake.paths().count("/api/v1/auth/service-token") == 1
    clock["now"] += 900 * 0.8 - 1  # token still good; the URLs too
    client.playback_url("77777777-0000-4000-8000-000000000003")
    assert fake.paths().count("/api/v1/auth/service-token") == 1
    clock["now"] += 2  # past 80% of the token's 900 s
    client.playback_url("77777777-0000-4000-8000-000000000004")
    assert fake.paths().count("/api/v1/auth/service-token") == 2


def test_unknown_clip_is_none_and_remembered_briefly(client, fake, clock, caplog):
    fake.clip_status[MEDIA] = 404  # e.g. a faked detection with a made-up media_id
    with caplog.at_level(logging.WARNING):
        assert client.playback_url(MEDIA) is None
    assert not caplog.records  # not a warning: a missing clip is normal
    assert client.playback_url(MEDIA) is None
    assert fake.paths().count(f"/api/v1/clips/{MEDIA}/playback-url") == 1
    clock["now"] += FAILURE_TTL_S + 1
    fake.clip_status.clear()
    assert client.playback_url(MEDIA) == f"https://s3.example/{MEDIA}.wav?sig"


@pytest.mark.parametrize(
    "setup",
    [
        lambda f: f.clip_status.update({MEDIA: 503}),  # C1 storage unavailable
        lambda f: f.clip_status.update({MEDIA: 403}),  # scope missing
        lambda f: setattr(f, "clip_error", httpx.ReadTimeout("slow")),
        lambda f: setattr(f, "clip_error", httpx.ConnectError("c1 down")),
        lambda f: setattr(f, "token_status", 401),  # C4 refuses the client
        lambda f: setattr(f, "body_override", "<html>bad gateway</html>"),
    ],
    ids=["c1-503", "c1-403", "timeout", "c1-down", "token-refused", "malformed"],
)
def test_any_failure_is_no_clip_with_a_warning(client, fake, setup, caplog):
    setup(fake)
    with caplog.at_level(logging.WARNING):
        assert client.playback_url(MEDIA) is None
    assert "clip playback URL unavailable" in caplog.text
    calls = len(fake.calls)
    assert client.playback_url(MEDIA) is None  # remembered: no new calls within FAILURE_TTL_S
    assert len(fake.calls) == calls


def test_failure_never_retries_within_one_lookup(client, fake):
    fake.clip_status[MEDIA] = 503
    client.playback_url(MEDIA)
    assert fake.paths().count(f"/api/v1/clips/{MEDIA}/playback-url") == 1


def test_made_from_settings_only_with_a_client_secret(settings):
    assert make_clip_client(settings) is None  # tests run without a secret
    built = make_clip_client(
        settings.model_copy(
            update={
                "service_client_secret": "s",
                "c1_base_url": "http://c1:8001",
                "c4_base_url": "http://c4:8004",
            }
        )
    )
    assert (built.c1_base_url, built.c4_base_url, built.client_id) == (
        "http://c1:8001",
        "http://c4:8004",
        "c2-alerts",
    )
