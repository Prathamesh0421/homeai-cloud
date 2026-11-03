"""BaseServiceSettings: shared vs per-service variables with one shared .env."""

from __future__ import annotations

from typing import ClassVar

import pytest
from homeai_common.config import BaseServiceSettings
from pydantic import Field
from pydantic_settings import SettingsConfigDict


class C2Settings(BaseServiceSettings):
    model_config = SettingsConfigDict(env_prefix="C2_", env_file=None, extra="ignore")
    service_code: ClassVar[str] = "c2"
    service_client_id: str | None = "c2-alerts"
    notifier: str = Field(default="log", validation_alias="NOTIFIER")
    alert_view_key_secret: str = "homeai/alert-view-hmac"


class C4Settings(BaseServiceSettings):
    model_config = SettingsConfigDict(env_prefix="C4_", env_file=None, extra="ignore")
    service_code: ClassVar[str] = "c4"


@pytest.fixture
def shared_env(monkeypatch):
    """What compose passes to every container from the one .env file."""
    env = {
        "ENV": "aws",
        "DEMO_MODE": "0",
        "AWS_REGION": "us-west-2",
        "AWS_ENDPOINT_URL": "http://localstack:4566",
        "S3_BUCKET": "homeai-team",
        "GIT_SHA": "abc123",
        "NOTIFIER": "sns",
        "DATABASE_URL_C2": "postgresql+psycopg://c2_app:pw@postgres:5432/homeai",
        "DATABASE_READER_URL_C2": "postgresql+psycopg://c2_reader:pw@postgres:5432/homeai",
        "DATABASE_URL_C4": "postgresql+psycopg://c4_app:pw@postgres:5432/homeai",
        "MONGO_URL_C4": "mongodb://c4_app:pw@mongo:27017/homeai",
        "SERVICE_CLIENT_SECRET_C2": "c2-secret",
        "SERVICE_CLIENT_SECRET_C4": "c4-secret",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return env


def test_each_service_picks_only_its_own_suffixed_vars(shared_env):
    c2 = C2Settings()
    c4 = C4Settings()
    assert c2.database_url == shared_env["DATABASE_URL_C2"]
    assert c2.database_reader_url == shared_env["DATABASE_READER_URL_C2"]
    assert c2.service_client_secret == "c2-secret"
    assert c2.mongo_url is None
    assert c4.database_url == shared_env["DATABASE_URL_C4"]
    assert c4.mongo_url == shared_env["MONGO_URL_C4"]
    assert c4.service_client_secret == "c4-secret"


def test_shared_vars_ignore_the_prefix(shared_env, monkeypatch):
    monkeypatch.setenv("C2_ENV", "ignored")
    c2 = C2Settings()
    assert c2.env == "aws"
    assert c2.demo_mode is False
    assert c2.s3_bucket == "homeai-team"
    assert c2.git_sha == "abc123"
    assert c2.notifier == "sns"
    assert not c2.is_local


def test_prefixed_var_wins_over_suffixed(shared_env, monkeypatch):
    monkeypatch.setenv("C2_DATABASE_URL", "postgresql+psycopg://override@x/homeai")
    assert C2Settings().database_url == "postgresql+psycopg://override@x/homeai"


def test_service_specific_prefixed_field(monkeypatch):
    monkeypatch.setenv("C2_ALERT_VIEW_KEY_SECRET", "custom/secret")
    assert C2Settings().alert_view_key_secret == "custom/secret"


def test_init_kwargs_win_and_field_names_work():
    s = C2Settings(env="test", database_url="sqlite://", demo_mode=True)
    assert s.env == "test"
    assert s.database_url == "sqlite://"
    assert s.demo_mode is True


def test_defaults_without_env(monkeypatch):
    for var in ("ENV", "AWS_ENDPOINT_URL", "DATABASE_URL_C2", "C2_DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    s = C2Settings()
    assert s.is_local
    assert s.service_client_id == "c2-alerts"
    assert s.database_url is None
    assert s.aws_endpoint is None


def test_empty_endpoint_means_real_aws(monkeypatch):
    monkeypatch.setenv("AWS_ENDPOINT_URL", "")
    assert C2Settings().aws_endpoint is None


def test_empty_suffixed_value_is_ignored(monkeypatch):
    monkeypatch.delenv("C2_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL_C2", "")
    assert C2Settings().database_url is None


def test_base_class_without_service_code_has_no_suffix_fallback(monkeypatch):
    monkeypatch.setenv("DATABASE_URL_", "nope")
    assert BaseServiceSettings().database_url is None
