"""C1 settings (env prefix ``C1_``; shared vars unprefixed — see homeai_common.config).

| Field | Env var(s) |
|---|---|
| database_url | ``C1_DATABASE_URL`` or ``DATABASE_URL_C1`` (role ``c1_app``) |
| mongo_url | ``C1_MONGO_URL`` or ``MONGO_URL_C1`` (``c1_app``: inserts ``media_events``) |
| max_upload_bytes | ``C1_MAX_UPLOAD_BYTES`` (default 50 MB; larger clips get 413) |
| presign_ttl_s | ``C1_PRESIGN_TTL_S`` (playback URL lifetime, default 15 min) |
| connectivity_interval_s | ``C1_CONNECTIVITY_INTERVAL_S`` (ConnectivityMonitor period, default 60 s) |
| jobs_enabled | ``C1_JOBS_ENABLED`` (ConnectivityMonitor in this process; default on) |
"""

from __future__ import annotations

from functools import lru_cache
from typing import ClassVar

from homeai_common.config import BaseServiceSettings
from pydantic_settings import SettingsConfigDict

SERVICE_NAME = "c1-iot"


class Settings(BaseServiceSettings):
    model_config = SettingsConfigDict(
        env_prefix="C1_", env_file=None, extra="ignore", populate_by_name=True
    )
    service_code: ClassVar[str] = "c1"

    database_url: str | None = "postgresql+psycopg://c1_app:devpass@postgres:5432/homeai"
    mongo_url: str | None = "mongodb://c1_app:devpass@mongo:27017/homeai"
    service_client_id: str | None = SERVICE_NAME

    max_upload_bytes: int = 50 * 1024 * 1024
    presign_ttl_s: int = 15 * 60
    connectivity_interval_s: int = 60
    # The scheduler takes a Postgres advisory lock per run, so several processes can have it on.
    # Tests turn it off and call the job directly.
    jobs_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
