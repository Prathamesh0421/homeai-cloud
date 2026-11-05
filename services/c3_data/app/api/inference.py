"""Inference endpoints. Static/test paths first (C3-05, docs §3.1).

``POST /inference/test`` runs the pipeline with no persistence and returns the home labels,
the raw YAMNet top-10, and timing. Access: cloud_staff or iot_staff.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from homeai_common.auth import require_roles
from homeai_common.errors import ApiError
from homeai_common.pagination import Envelope, data_response
from pymongo.database import Database
from sqlalchemy.orm import Session

from app.api.deps import build_pipeline, get_model_cache, get_mongo, get_session
from app.ml.audio import UnreadableClipError
from app.ml.model_cache import ModelCache
from app.repositories.media_event_repo import COLLECTION as EV_COLLECTION
from app.repositories.media_event_repo import MediaEventRepo
from app.repositories.ml_model_repo import MlModelRepo
from app.schemas.inference import ClassifyRequest, ClassifyResult, TestClassifyResult
from app.services.classification_pipeline import DetectionExistsError, classify_bytes

router = APIRouter(prefix="/api/v1/inference", tags=["inference"])

cs_or_is = require_roles("cloud_staff", "iot_staff")
cloud = require_roles("cloud_staff")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB (docs §3.1)


@router.post("/test", response_model=Envelope[TestClassifyResult], dependencies=[Depends(cs_or_is)])
async def test_classify(
    file: UploadFile = File(...),
    model_id: str | None = Form(default=None),
    session: Session = Depends(get_session),
    cache: ModelCache = Depends(get_model_cache),
) -> dict:
    """Classify an uploaded clip against the active (or given) model. No persistence."""
    repo = MlModelRepo(session)
    model = repo.get(model_id) if model_id else repo.get_active()
    if model is None:
        raise ApiError(404, "not_found", "model not found")

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "payload_too_large", "clip exceeds 20 MB")

    cache.ensure(model.model_id, model.label_map)
    try:
        result = classify_bytes(raw, cache.runner, cache.mapper, model.label_map)
    except UnreadableClipError as exc:
        raise ApiError(422, "unreadable_clip", str(exc)) from exc

    return data_response(
        TestClassifyResult(
            model={"model_id": model.model_id, "name": model.name, "version": model.version},
            top_label=result.top_label,
            top_confidence=result.top_confidence,
            labels=[
                {
                    "label": label.label,
                    "confidence": label.confidence,
                    "source_class": label.source_class,
                    "start_s": label.start_s,
                    "end_s": label.end_s,
                }
                for label in result.labels
            ],
            raw_top10=[{"class_name": r.class_name, "score": r.score} for r in result.raw_top10],
            frames=result.frames,
            duration_s=result.duration_s,
            latency_ms=result.latency_ms,
        )
    )


@router.post("/classify", response_model=Envelope[ClassifyResult], dependencies=[Depends(cloud)])
def classify_stored(
    body: ClassifyRequest,
    request: Request,
    session: Session = Depends(get_session),
    mdb: Database = Depends(get_mongo),
    cache: ModelCache = Depends(get_model_cache),
) -> dict:
    """Re-run the pipeline for a stored clip. 404 if unknown; 409 already_analyzed unless force."""
    model = MlModelRepo(session).get_active()
    if model is None:
        raise ApiError(404, "not_found", "no active model")

    pipeline = build_pipeline(request, mdb)
    events = MediaEventRepo(mdb[EV_COLLECTION])
    ev = events.get(body.media_id)
    if ev is None:
        raise ApiError(404, "not_found", "media event not found")

    model_dict = {"model_id": model.model_id, "name": model.name, "version": model.version}
    cache.ensure(model.model_id, model.label_map, warm_up=False)
    try:
        detection = pipeline.classify(
            ev, model_dict, cache.runner, cache.mapper, model.label_map, force=body.force
        )
    except DetectionExistsError as exc:
        raise ApiError(409, "already_analyzed", "clip already analyzed; pass force") from exc
    except UnreadableClipError as exc:
        raise ApiError(422, "unreadable_clip", str(exc)) from exc

    return data_response(
        ClassifyResult(
            detection_id=detection["_id"],
            media_id=detection["media_id"],
            top_label=detection["top_label"],
            top_confidence=detection["top_confidence"],
            labels=[
                {
                    "label": label["label"],
                    "confidence": label["confidence"],
                    "source_class": label["source_class"],
                    "start_s": label["start_s"],
                    "end_s": label["end_s"],
                }
                for label in detection["labels"]
            ],
            handoff_status=(events.get(body.media_id) or {}).get("handoff_status", "none"),
        )
    )
