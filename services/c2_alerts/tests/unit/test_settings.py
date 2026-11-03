"""C2 settings read the shared .env layout (docs/03 §5)."""

from __future__ import annotations

import pytest
from app.main import default_checks
from app.settings import Settings
from pydantic import ValidationError


@pytest.fixture
def env(monkeypatch):
    values = {
        "DATABASE_URL_C2": "postgresql+psycopg://c2_app:pw@postgres:5432/homeai",
        "DATABASE_READER_URL_C2": "postgresql+psycopg://c2_reader:pw@postgres:5432/homeai",
        "DATABASE_URL_C4": "postgresql+psycopg://c4_app:pw@postgres:5432/homeai",
        "MONGO_URL_C2_READER": "mongodb://c2_reader:pw@mongo:27017/homeai",
        "SERVICE_CLIENT_SECRET_C2": "c2-secret",
        "C2_ALERT_VIEW_KEY_SECRET": "homeai/alert-view-hmac-test",
        "NOTIFIER": "sns",
        "C1_BASE_URL": "http://c1:8001",
        "GIT_SHA": "abc",
    }
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("C2_DATABASE_URL", raising=False)
    return values


def test_reads_c2_vars_from_shared_env(env):
    s = Settings()
    assert s.database_url == env["DATABASE_URL_C2"]
    assert s.database_reader_url == env["DATABASE_READER_URL_C2"]
    assert s.mongo_reader_url == env["MONGO_URL_C2_READER"]
    assert s.service_client_id == "c2-alerts"
    assert s.service_client_secret == "c2-secret"
    assert s.alert_view_key_secret == "homeai/alert-view-hmac-test"
    assert s.notifier == "sns"
    assert s.c1_base_url == "http://c1:8001"
    assert s.git_sha == "abc"


def test_defaults(monkeypatch):
    for var in ("NOTIFIER", "MONGO_URL_C2_READER", "DATABASE_URL_C2", "C2_DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.notifier == "log"
    assert s.mongo_reader_url is None
    assert s.database_url.startswith("postgresql+psycopg://c2_app")


def test_unknown_notifier_rejected(monkeypatch):
    monkeypatch.setenv("NOTIFIER", "carrier-pigeon")
    with pytest.raises(ValidationError):
        Settings()


def test_default_checks_include_mongo_only_when_configured(env):
    assert set(default_checks(Settings())) == {"db", "mongo"}
    assert set(default_checks(Settings(mongo_reader_url=None))) == {"db"}


def test_detection_reader_wiring():
    from app.api.deps import get_app_settings, get_detection_reader
    from app.gateways.detection_gateway import MongoDetectionGateway

    class _Req:
        class app:
            class state:
                settings = Settings(mongo_reader_url="mongodb://localhost:1/homeai")

    settings = get_app_settings(_Req())
    reader = get_detection_reader(settings)
    assert isinstance(reader, MongoDetectionGateway)
    assert reader.collection.full_name == "homeai.ai_detections"
    assert get_detection_reader(Settings(mongo_reader_url=None)) is None


def test_settings_reader_and_clock_providers():
    from app.api.deps import get_clock, get_settings_reader
    from app.gateways.c4_settings_gateway import C4SettingsGateway

    sentinel = object()
    reader = get_settings_reader(sentinel)
    assert isinstance(reader, C4SettingsGateway) and reader.session is sentinel
    assert get_clock()().utcoffset().total_seconds() == 0
