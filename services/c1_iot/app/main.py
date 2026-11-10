"""C1 FastAPI app factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI
from homeai_common import db, mongo
from homeai_common.auth import configure_jwks
from homeai_common.errors import install_error_handlers
from homeai_common.health import HealthCheck, health_router
from homeai_common.logging import RequestIdMiddleware, configure_logging

from app.api import feeds, houses
from app.db.mongo_indexes import MEDIA_EVENTS, ensure_indexes
from app.settings import SERVICE_NAME, Settings, get_settings

logger = logging.getLogger(__name__)


def default_checks(settings: Settings) -> dict[str, HealthCheck]:
    """Postgres (own role) and Mongo (``media_events``)."""
    checks: dict[str, HealthCheck] = {"db": db.check_database}
    if settings.mongo_url:
        url = settings.mongo_url
        checks["mongo"] = lambda: mongo.check_mongo(mongo.get_mongo_db(url))
    return checks


def _ensure_mongo_indexes(settings: Settings) -> None:
    """Best effort: a Mongo outage must not stop the API from starting (health shows it)."""
    if not settings.mongo_url:
        return
    try:
        ensure_indexes(mongo.get_mongo_db(settings.mongo_url)[MEDIA_EVENTS])
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("media_events indexes not ensured", extra={"error": str(exc)[:200]})


def create_app(
    settings: Settings | None = None, checks: Mapping[str, HealthCheck] | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(SERVICE_NAME, settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Engines and JWKS fetches are lazy: startup never needs the network except for the
        # best-effort Mongo index creation.
        if settings.database_url:
            db.configure_db(settings.database_url)
        configure_jwks(settings.jwks_url)
        if settings.jobs_enabled:
            _ensure_mongo_indexes(settings)
        yield
        db.dispose_db()
        mongo.close_mongo()

    app = FastAPI(
        title="HomeAI Cloud — C1 Home-Based IoT Device Manager",
        version="0.1.0",
        docs_url="/api/v1/docs/c1",
        redoc_url=None,
        openapi_url="/api/v1/docs/c1/openapi.json",
        swagger_ui_parameters={"persistAuthorization": True},
        lifespan=lifespan,
    )
    app.state.settings = settings
    install_error_handlers(app)
    app.add_middleware(RequestIdMiddleware)

    app.include_router(
        health_router(
            "c1",
            checks if checks is not None else default_checks(settings),
            version=settings.git_sha,
        )
    )
    app.include_router(houses.router)
    app.include_router(feeds.router)
    return app
