"""C2 settings (env prefix ``C2_``; shared vars unprefixed — see homeai_common.config).

| Field | Env var(s) |
|---|---|
| database_url | ``C2_DATABASE_URL`` or ``DATABASE_URL_C2`` (role ``c2_app``) |
| database_reader_url | ``C2_DATABASE_READER_URL`` or ``DATABASE_READER_URL_C2`` (role ``c2_reader``: c4 settings/contacts, c1 houses/rooms) |
| mongo_reader_url | ``MONGO_URL_C2_READER`` (read-only ``ai_detections``) |
| service_client_secret | ``C2_SERVICE_CLIENT_SECRET`` or ``SERVICE_CLIENT_SECRET_C2`` |
| notifier | ``NOTIFIER`` (``log`` locally, ``sns`` on AWS) |
| alert_view_key_secret | ``C2_ALERT_VIEW_KEY_SECRET`` (Secrets Manager id of the HMAC key) |
| alert_view_key | ``C2_ALERT_VIEW_KEY`` (base64 key; local override of Secrets Manager) |
| c1_base_url | ``C1_BASE_URL`` (playback URLs) |
"""

from __future__ import annotations

from functools import lru_cache
from typing import ClassVar, Literal

from homeai_common.config import BaseServiceSettings
from pydantic import Field
from pydantic_settings import SettingsConfigDict

SERVICE_NAME = "c2-alerts"


class Settings(BaseServiceSettings):
    model_config = SettingsConfigDict(
        env_prefix="C2_", env_file=None, extra="ignore", populate_by_name=True
    )
    service_code: ClassVar[str] = "c2"

    database_url: str | None = "postgresql+psycopg://c2_app:devpass@postgres:5432/homeai"
    database_reader_url: str | None = None
    mongo_reader_url: str | None = Field(default=None, validation_alias="MONGO_URL_C2_READER")
    service_client_id: str | None = SERVICE_NAME

    notifier: Literal["log", "sns"] = Field(default="log", validation_alias="NOTIFIER")
    alert_view_key_secret: str = "homeai/alert-view-hmac"
    # Local override for the HMAC key (base64), skipping Secrets Manager: C2_ALERT_VIEW_KEY.
    alert_view_key: str | None = None
    alert_view_rate_limit_per_min: int = 60
    c1_base_url: str = Field(default="http://c1-iot:8001", validation_alias="C1_BASE_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
