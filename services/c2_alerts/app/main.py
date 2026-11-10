"""C2 FastAPI app factory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from homeai_common import db, mongo
from homeai_common.auth import configure_jwks
from homeai_common.errors import error_envelope, install_error_handlers
from homeai_common.health import HealthCheck, health_router
from homeai_common.logging import RequestIdMiddleware, configure_logging

from app.api import alert_view, alerts, rules
from app.gateways.c1_clip_client import make_clip_client
from app.gateways.notifier import LogNotifier, Notifier
from app.gateways.secrets_gateway import AlertViewKeyProvider
from app.gateways.sns_gateway import SnsGateway
from app.gateways.types import DependencyUnavailableError
from app.jobs.runner import JobRunner, start_scheduler
from app.services.rate_limit import SlidingWindowLimiter
from app.services.signed_link import SignedLinkService
from app.settings import SERVICE_NAME, Settings, get_settings


def default_checks(settings: Settings) -> dict[str, HealthCheck]:
    """Postgres (own role) and the read-only Mongo used for detections."""
    checks: dict[str, HealthCheck] = {"db": db.check_database}
    if settings.mongo_reader_url:
        url = settings.mongo_reader_url
        checks["mongo"] = lambda: mongo.check_mongo(mongo.get_mongo_db(url))
    return checks


async def _dependency_unavailable(_: Request, exc: DependencyUnavailableError) -> JSONResponse:
    # 503 so callers (C3's handoff, the SPA) retry; details name the source that is down.
    return JSONResponse(
        status_code=503,
        content=error_envelope(
            "dependency_unavailable", f"{exc.source} is unavailable", {"source": exc.source}
        ),
    )


def make_notifier(settings: Settings) -> Notifier:
    if settings.notifier == "sns":
        return SnsGateway(region=settings.aws_region, endpoint_url=settings.aws_endpoint)
    return LogNotifier()


def create_app(
    settings: Settings | None = None, checks: Mapping[str, HealthCheck] | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(SERVICE_NAME, settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Engines, Mongo clients and JWKS fetches are lazy: startup never needs the network.
        if settings.database_url:
            db.configure_db(settings.database_url, reader_url=settings.database_reader_url)
        configure_jwks(settings.jwks_url)
        scheduler = None
        if settings.jobs_enabled and settings.database_url:
            scheduler = start_scheduler(app.state.jobs)
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=True)  # let a running job finish before the engines go
        db.dispose_db()
        mongo.close_mongo()

    app = FastAPI(
        title="HomeAI Cloud — C2 Alert Tracking and Monitor",
        version="0.1.0",
        docs_url="/api/v1/docs/c2",
        redoc_url=None,
        openapi_url="/api/v1/docs/c2/openapi.json",
        swagger_ui_parameters={"persistAuthorization": True},
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.links = SignedLinkService(
        keys=AlertViewKeyProvider(
            secret_id=settings.alert_view_key_secret,
            region=settings.aws_region,
            endpoint_url=settings.aws_endpoint,
            override_b64=settings.alert_view_key,
            demo_mode=settings.demo_mode,
        ),
        public_base_url=settings.public_base_url,
    )
    app.state.notifier = make_notifier(settings)
    app.state.clips = make_clip_client(settings)
    app.state.jobs = JobRunner(notifier=app.state.notifier, links=app.state.links)
    app.state.alert_view_limiter = SlidingWindowLimiter(
        settings.alert_view_rate_limit_per_min, window_s=60
    )
    install_error_handlers(app)
    app.add_exception_handler(DependencyUnavailableError, _dependency_unavailable)
    app.add_middleware(RequestIdMiddleware)

    app.include_router(
        health_router(
            "c2",
            checks if checks is not None else default_checks(settings),
            version=settings.git_sha,
        )
    )
    app.include_router(alerts.router)
    app.include_router(alert_view.router)
    app.include_router(rules.router)
    return app
