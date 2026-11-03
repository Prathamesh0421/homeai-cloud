"""Shared service settings (docs/03_REPO_AND_INFRA.md §2, §5).

Compose hands one shared ``.env`` to every container, so variables come in two kinds:

* **Shared** (same for every service, unprefixed): ``ENV``, ``PUBLIC_BASE_URL``, ``DEMO_MODE``,
  ``AWS_REGION``, ``AWS_ENDPOINT_URL``, ``AWS_PUBLIC_ENDPOINT_URL``, ``S3_BUCKET``, ``JWKS_URL``,
  ``C4_BASE_URL``, ``GIT_SHA``, ``LOG_LEVEL``.
* **Per service** (``database_url``, ``database_reader_url``, ``mongo_url``,
  ``service_client_id``, ``service_client_secret``): read from ``<PREFIX><NAME>``
  (e.g. ``C2_DATABASE_URL``) or, failing that, from ``<NAME>_<CODE>`` as written in
  ``.env.example`` (e.g. ``DATABASE_URL_C2``). The prefixed form wins.

Subclass once per service::

    class Settings(BaseServiceSettings):
        model_config = SettingsConfigDict(env_prefix="C2_", env_file=None, extra="ignore")
        service_code: ClassVar[str] = "c2"
        service_client_id: str = "c2-alerts"
        notifier: str = Field(default="log", validation_alias="NOTIFIER")   # shared var
        alert_view_key_secret: str = "homeai/alert-view-hmac"               # C2_ALERT_VIEW_KEY_SECRET
"""

from __future__ import annotations

import os
from typing import Any, ClassVar

from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

PER_SERVICE_FIELDS: tuple[str, ...] = (
    "database_url",
    "database_reader_url",
    "mongo_url",
    "service_client_id",
    "service_client_secret",
)


def _shared(name: str, default: Any) -> Any:
    """A field read from one unprefixed env var, whatever the subclass's env_prefix is."""
    return Field(default=default, validation_alias=name)


class _SuffixedEnvSource(PydanticBaseSettingsSource):
    """Reads ``DATABASE_URL_C2``-style variables for the per-service fields."""

    def __init__(self, settings_cls: type[BaseSettings]):
        super().__init__(settings_cls)
        code = getattr(settings_cls, "service_code", "") or ""
        self.suffix = f"_{code.upper()}" if code else ""

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        if not self.suffix or field_name not in PER_SERVICE_FIELDS:
            return None, field_name, False
        value = os.environ.get(f"{field_name.upper()}{self.suffix}")
        return value, field_name, False

    def __call__(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for name, field in self.settings_cls.model_fields.items():
            value, key, _ = self.get_field_value(field, name)
            if value not in (None, ""):
                values[key] = value
        return values


class BaseServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None, extra="ignore", populate_by_name=True, case_sensitive=False
    )

    # Lowercase component code ("c1".."c4"); drives the DATABASE_URL_<CODE> fallback.
    service_code: ClassVar[str] = ""

    # Shared
    env: str = _shared("ENV", "local")
    public_base_url: str = _shared("PUBLIC_BASE_URL", "http://localhost:8080")
    demo_mode: bool = _shared("DEMO_MODE", False)
    aws_region: str = _shared("AWS_REGION", "us-west-2")
    aws_endpoint_url: str | None = _shared("AWS_ENDPOINT_URL", None)
    # Browser-reachable S3 endpoint for presigned URLs (LocalStack: http://localhost:4566).
    aws_public_endpoint_url: str | None = _shared("AWS_PUBLIC_ENDPOINT_URL", None)
    s3_bucket: str = _shared("S3_BUCKET", "homeai-local")
    jwks_url: str = _shared("JWKS_URL", "http://c4-dashboard:8004/.well-known/jwks.json")
    c4_base_url: str = _shared("C4_BASE_URL", "http://c4-dashboard:8004")
    git_sha: str = _shared("GIT_SHA", "dev")
    log_level: str = _shared("LOG_LEVEL", "INFO")

    # Per service
    database_url: str | None = None
    database_reader_url: str | None = None
    mongo_url: str | None = None
    service_client_id: str | None = None
    service_client_secret: str | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            _SuffixedEnvSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )

    @property
    def aws_endpoint(self) -> str | None:
        """``AWS_ENDPOINT_URL`` with empty strings treated as unset (real AWS)."""
        return self.aws_endpoint_url or None

    @property
    def is_local(self) -> bool:
        return self.env == "local"
