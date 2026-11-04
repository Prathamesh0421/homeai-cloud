"""C3 FastAPI app factory. Mirrors C2's create_app pattern."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI
from homeai_common import db, mongo
from homeai_common.auth import configure_jwks
from homeai_common.errors import install_error_handlers
from homeai_common.health import HealthCheck, health_router
from homeai_common.logging import RequestIdMiddleware, configure_logging

from app.db.mongo_indexes import ensure_indexes
from app.settings import SERVICE_NAME, Settings, get_settings


def default_checks(settings: Settings) -> dict[str, HealthCheck]:
    """Postgres (own c3_app role) and the Mongo C3 reads/writes (detections)."""
    checks: dict[str, HealthCheck] = {"db": db.check_database}
    if settings.mongo_url:
        url = settings.mongo_url
        checks["mongo"] = lambda: mongo.check_mongo(mongo.get_mongo_db(url))
    return checks


def create_app(
    settings: Settings | None = None, checks: Mapping[str, HealthCheck] | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(SERVICE_NAME, settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Engines, Mongo clients and JWKS fetches are lazy: startup never needs the network.
        if settings.database_url:
            db.configure_db(settings.database_url, reader_url=settings.database_reader_url)
        if settings.mongo_url:
            # Idempotent; creates C3-owned indexes (ai_detections, activity_patterns,
            # worker_heartbeats TTL). Tolerate Mongo being unreachable at startup so the
            # API can still serve health/docs and report a degraded Mongo check.
            with contextlib.suppress(Exception):
                ensure_indexes(mongo.get_mongo_db(settings.mongo_url))
        configure_jwks(settings.jwks_url)
        yield
        db.dispose_db()
        mongo.close_mongo()

    app = FastAPI(
        title="HomeAI Cloud — C3 System Database Management and AI inference",
        version="0.1.0",
        docs_url="/api/v1/docs/c3",
        redoc_url=None,
        openapi_url="/api/v1/docs/c3/openapi.json",
        swagger_ui_parameters={"persistAuthorization": True},
        lifespan=lifespan,
    )
    app.state.settings = settings
    install_error_handlers(app)
    app.add_middleware(RequestIdMiddleware)

    app.include_router(
        health_router(
            "c3",
            checks if checks is not None else default_checks(settings),
            version=settings.git_sha,
        )
    )
    # Feature routers (inference, models, records, ...) are added in later phases.
    return app
