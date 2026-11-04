"""FastAPI dependencies shared by C3 routers (tests override these)."""

from __future__ import annotations

from fastapi import Request
from homeai_common import db

from app.ml.model_cache import ModelCache
from app.settings import Settings

# Read/write session as c3_app.
get_session = db.get_session


def get_app_settings(request: Request) -> Settings:
    """The Settings ``create_app`` was built with (tests pass their own)."""
    return request.app.state.settings


def get_model_cache(request: Request) -> ModelCache:
    """Process-level YAMNet + label-map cache, built once in ``create_app``."""
    return request.app.state.model_cache
