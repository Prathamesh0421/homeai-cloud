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


def get_reader_connection(request: Request):
    """A read-only (c3_reader) SQLAlchemy Connection for cross-component reads, or None.

    None when DATABASE_READER_URL_C3 is not set; the Records API treats SQL entities as
    unavailable in that case (c1/c2 reads need the reader role).
    """
    try:
        db.get_engine(db.READER)
    except RuntimeError:
        yield None
        return
    with db.get_engine(db.READER).connect() as conn:
        yield conn


def get_records_limiter(request: Request):
    """Per-user sliding-window limiter for the Records API (built once in create_app)."""
    return request.app.state.records_limiter


def build_pipeline(request: Request, mdb: Database):
    """A ClassificationPipeline wired to S3, the Mongo repos, and the HANDOFF_MODE hook.

    Used by the synchronous classify/re-classify API path (the worker builds its own).
    """
    from app.gateways.alert_handoff_client import build_handoff
    from app.gateways.s3_gateway import S3ClipGateway
    from app.repositories.detection_repo import COLLECTION as DET
    from app.repositories.detection_repo import DetectionRepo
    from app.repositories.media_event_repo import COLLECTION as EV
    from app.repositories.media_event_repo import MediaEventRepo
    from app.services.activity_service import build_rollup
    from app.services.classification_pipeline import ClassificationPipeline

    settings: Settings = request.app.state.settings
    s3 = S3ClipGateway(settings.s3_bucket, settings.aws_region, settings.aws_endpoint)
    return ClassificationPipeline(
        s3_get=s3.get_bytes,
        detection_repo=DetectionRepo(mdb[DET]),
        media_event_repo=MediaEventRepo(mdb[EV]),
        on_detection=build_handoff(settings),
        on_rollup=build_rollup(mdb),
    )
