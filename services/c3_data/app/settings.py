"""C3 service settings (env prefix ``C3_``). Mirrors C2's settings pattern."""

from __future__ import annotations

from functools import lru_cache
from typing import ClassVar, Literal

from homeai_common.config import BaseServiceSettings
from pydantic import Field
from pydantic_settings import SettingsConfigDict

SERVICE_NAME = "c3-data"


class Settings(BaseServiceSettings):
    model_config = SettingsConfigDict(
        env_prefix="C3_", env_file=None, extra="ignore", populate_by_name=True
    )
    service_code: ClassVar[str] = "c3"

    # PostgreSQL (schema c3, owner role c3_app) and its read-only role.
    database_url: str | None = "postgresql+psycopg://c3_app:devpass@postgres:5432/homeai"
    database_reader_url: str | None = None

    # MongoDB — C3 owns ai_detections / activity_patterns / worker_heartbeats and
    # updates C1's media_events processing fields, so it uses a read/write URL.
    mongo_url: str | None = Field(default=None, validation_alias="MONGO_URL_C3")

    service_client_id: str | None = SERVICE_NAME

    # Where the bundled YAMNet SavedModel lives inside the image (see Dockerfile).
    model_dir: str = Field(default="/models", validation_alias="C3_MODEL_DIR")

    # Alert handoff to C2: "log" prints the payload (independent dev); "call" POSTs
    # to C2's /alerts/evaluate. Kept "log" until C2 integration (Phase 7).
    handoff_mode: Literal["call", "log"] = Field(default="log", validation_alias="HANDOFF_MODE")
    c2_base_url: str = Field(default="http://c2-alerts:8002", validation_alias="C2_BASE_URL")

    # Worker loop timing (seconds).
    worker_heartbeat_interval: int = 10
    worker_sleep: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
