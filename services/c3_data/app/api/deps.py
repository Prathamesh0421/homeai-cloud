"""FastAPI dependencies shared by C3 routers (tests override these)."""

from __future__ import annotations

from fastapi import Request
from homeai_common import db, mongo
from homeai_common.errors import ApiError
from pymongo.database import Database

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


def get_class_names(request: Request) -> list[str]:
    """YAMNet 521 class display names, loaded once in ``create_app`` (tests may inject)."""
    return request.app.state.class_names


def get_mongo(request: Request) -> Database:
    """C3's Mongo database handle, or 503 if MONGO_URL is not configured."""
    settings: Settings = request.app.state.settings
    if not settings.mongo_url:
        raise ApiError(503, "dependency_unavailable", "mongo not configured")
    return mongo.get_mongo_db(settings.mongo_url)
