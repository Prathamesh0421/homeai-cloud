"""C4 service settings (env prefix C4_).

Until P0-3 lands `homeai_common.config.BaseServiceSettings`, C4 keeps its own
pydantic-settings class. The fields mirror docs/03_REPO_AND_INFRA.md §5.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="C4_", env_file=None, extra="ignore")

    env: str = "local"
    public_base_url: str = "http://localhost:8080"
    demo_mode: bool = False

    # Database / Mongo
    database_url: str = "postgresql+psycopg://c4_app:devpass@postgres:5432/homeai"
    mongo_url: str = "mongodb://c4_app:devpass@mongo:27017/homeai"

    # JWT signing key
    jwt_private_key_secret: str = "homeai/jwt-signing-key"
    jwt_private_key_pem: str | None = None  # for local dev/tests without Secrets Manager
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

    # AWS
    aws_region: str = "us-west-2"
    aws_endpoint_url: str | None = "http://localstack:4566"

    # Git sha for health
    git_sha: str = "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
