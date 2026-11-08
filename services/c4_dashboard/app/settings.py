"""C4 service settings (env prefix C4_).

Uses ``homeai_common.config.BaseServiceSettings`` so shared compose vars
(``DEMO_MODE``, ``AWS_ENDPOINT_URL``, ``DATABASE_URL_C4``, …) are read without
the ``C4_`` prefix. On AWS, ``AWS_ENDPOINT_URL`` must be empty/unset so Secrets
Manager and SNS hit real AWS (not LocalStack).
"""

from __future__ import annotations

from functools import lru_cache
from typing import ClassVar

from homeai_common.config import BaseServiceSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseServiceSettings):
    model_config = SettingsConfigDict(env_prefix="C4_", env_file=None, extra="ignore")
    service_code: ClassVar[str] = "c4"

    # JWT signing key (C4_JWT_* or local PEM override)
    jwt_private_key_secret: str = "homeai/jwt-signing-key"
    jwt_private_key_pem: str | None = None
    jwt_kid: str = "2026-11"
    jwt_user_ttl_seconds: int = 3600
    jwt_service_ttl_seconds: int = 900

    # Inter-service URLs
    c1_base_url: str = "http://c1-iot:8001"
    c2_base_url: str = "http://c2-alerts:8002"
    c3_base_url: str = "http://c3-data:8003"

    # Lockout policy
    lockout_failure_threshold: int = 5
    lockout_window_seconds: int = 15 * 60
    lockout_duration_seconds: int = 15 * 60

    # Rate limit (informational; enforced by gateway in production)
    login_rate_limit_per_minute: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
