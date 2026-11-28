"""Unit tests for C4's cached c4-dashboard service token (contracts §2.3)."""

from __future__ import annotations

import pytest
from app.errors import ApiError
from app.services.service_token import (
    STATS_SCOPES,
    StatsTokenProvider,
    get_stats_token_provider,
    reset_stats_token_provider,
)
from app.settings import Settings


class FakeMinter:
    def __init__(self, ttl: int = 900):
        self.ttl = ttl
        self.calls: list[tuple[str, str, list[str]]] = []

    def __call__(self, client_id: str, secret: str, scopes: list[str]) -> tuple[str, int]:
        self.calls.append((client_id, secret, scopes))
        return f"tok-{len(self.calls)}", self.ttl


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _provider(minter, clock, secret: str | None = "s3cret") -> StatsTokenProvider:
    return StatsTokenProvider(
        client_id="c4-dashboard", client_secret=secret, minter=minter, clock=clock
    )


def test_mints_with_c4_client_and_stats_scopes():
    minter = FakeMinter()
    assert _provider(minter, Clock()).token() == "tok-1"
    assert minter.calls == [
        ("c4-dashboard", "s3cret", ["feeds:read", "alerts:read", "records:read"])
    ]
    assert set(STATS_SCOPES) == {"feeds:read", "alerts:read", "records:read"}


def test_caches_until_80_percent_of_ttl():
    minter, clock = FakeMinter(ttl=900), Clock()
    p = _provider(minter, clock)
    assert p.token() == "tok-1"
    clock.now += 719
    assert p.token() == "tok-1"
    clock.now += 1  # 720 s = 80% of 900
    assert p.token() == "tok-2"
    assert len(minter.calls) == 2


def test_invalidate_forces_new_token():
    minter = FakeMinter()
    p = _provider(minter, Clock())
    p.token()
    p.invalidate()
    assert p.token() == "tok-2"


def test_missing_secret_fails_without_minting():
    minter = FakeMinter()
    with pytest.raises(ApiError) as exc:
        _provider(minter, Clock(), secret=None).token()
    assert exc.value.status_code == 503
    assert minter.calls == []


def test_process_provider_reads_settings(monkeypatch):
    monkeypatch.setenv("SERVICE_CLIENT_SECRET_C4", "from-env")
    reset_stats_token_provider()
    try:
        p = get_stats_token_provider(Settings())
        assert p.client_id == "c4-dashboard"
        assert p.client_secret == "from-env"
        assert get_stats_token_provider(Settings()) is p
    finally:
        reset_stats_token_provider()
