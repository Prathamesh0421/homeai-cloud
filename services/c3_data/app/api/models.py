"""Model management and deployment endpoints (C3-07/08, docs §3.1).

Route order matters (AGENTS.md): the static paths /models/active, /models/classes and
/models/deployment are declared BEFORE the parameterised /models/{model_id}.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from homeai_common.auth import Principal, require_roles
from homeai_common.errors import ApiError
from homeai_common.pagination import Envelope, data_response
from pymongo.database import Database
from sqlalchemy.orm import Session

from app.api.deps import (
    get_app_settings,
    get_class_names,
    get_mongo,
    get_session,
)
from app.gateways.s3_gateway import S3ClipGateway
from app.ml.evaluator import ModelEvaluator, summary
from app.ml.model_cache import ModelCache
from app.repositories.ml_model_repo import MlModelRepo
from app.schemas.models import (
    ActivateRequest,
    ClassesResponse,
    CreateModelRequest,
    DeploymentStatus,
    EvaluateRequest,
    ModelDetail,
    ModelSummary,
)
from app.services.deployment_status import build_deployment_status
from app.services.model_registry import ModelRegistry
from app.settings import Settings

router = APIRouter(prefix="/api/v1/models", tags=["models"])

cloud = require_roles("cloud_staff")
cloud_or_iot = require_roles("cloud_staff", "iot_staff")

SYSTEM_UUID = "00000000-0000-0000-0000-000000000000"


def _registry(session: Session, class_names: list[str]) -> ModelRegistry:
    return ModelRegistry(MlModelRepo(session), class_names)


def _summary(model) -> dict[str, Any]:
    return {
        "model_id": model.model_id,
        "name": model.name,
        "version": model.version,
        "status": model.status,
        "source": model.source,
        "metrics": model.metrics,
        "created_at": model.created_at,
        "activated_at": model.activated_at,
    }


def _detail(model, evaluations: list) -> dict[str, Any]:
    return {
        **_summary(model),
        "label_map": model.label_map,
        "notes": model.notes,
        "evaluations": [
            {
                "evaluation_id": e.evaluation_id,
                "dataset": e.dataset,
                "metrics": e.metrics,
                "started_at": e.started_at,
                "finished_at": e.finished_at,
            }
            for e in evaluations
        ],
    }


# --- static paths first ---------------------------------------------------
@router.get("", response_model=Envelope[list[ModelSummary]], dependencies=[Depends(cloud)])
def list_models(
    name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> dict:
    models = MlModelRepo(session).list(name=name, status=status)
    return data_response([_summary(m) for m in models])


@router.get("/active", response_model=Envelope[ModelDetail], dependencies=[Depends(cloud_or_iot)])
def get_active(session: Session = Depends(get_session)) -> dict:
    repo = MlModelRepo(session)
    model = repo.get_active()
    if model is None:
        raise ApiError(404, "not_found", "no active model")
    return data_response(_detail(model, repo.evaluations_for(model.model_id)))


@router.get("/classes", response_model=Envelope[ClassesResponse], dependencies=[Depends(cloud)])
def list_classes(
    q: str | None = Query(default=None),
    class_names: list[str] = Depends(get_class_names),
) -> dict:
    names = class_names
    if q:
        ql = q.lower()
        names = [c for c in class_names if ql in c.lower()]
    return data_response({"classes": names})


@router.get("/deployment", response_model=Envelope[DeploymentStatus], dependencies=[Depends(cloud)])
def deployment(
    session: Session = Depends(get_session),
    mdb: Database = Depends(get_mongo),
) -> dict:
    model = MlModelRepo(session).get_active()
    active = {"id": model.model_id, "version": model.version} if model else None
    return data_response(build_deployment_status(mdb, active))


# --- parameterised paths --------------------------------------------------
@router.get("/{model_id}", response_model=Envelope[ModelDetail], dependencies=[Depends(cloud)])
def get_model(model_id: str, session: Session = Depends(get_session)) -> dict:
    repo = MlModelRepo(session)
    model = repo.get(model_id)
    if model is None:
        raise ApiError(404, "not_found", "model not found")
    return data_response(_detail(model, repo.evaluations_for(model_id)))


@router.post("", response_model=Envelope[ModelDetail], status_code=201)
def create_model(
    body: CreateModelRequest,
    principal: Principal = Depends(cloud),
    session: Session = Depends(get_session),
    class_names: list[str] = Depends(get_class_names),
) -> dict:
    reg = _registry(session, class_names)
    label_map = body.label_map.model_dump() if body.label_map else None
    model = reg.create_version(
        name=body.name,
        version=body.version,
        created_by=principal.sub,
        base_model_id=body.base_model_id,
        label_map=label_map,
        notes=body.notes,
    )
    session.commit()
    return data_response(_detail(model, []))


@router.put(
    "/{model_id}/label-map", response_model=Envelope[ModelDetail], dependencies=[Depends(cloud)]
)
def update_label_map(
    model_id: str,
    body: dict,
    session: Session = Depends(get_session),
    class_names: list[str] = Depends(get_class_names),
) -> dict:
    reg = _registry(session, class_names)
    model = reg.update_label_map(model_id, body)
    session.commit()
    return data_response(_detail(model, []))


@router.post("/{model_id}/evaluate", response_model=Envelope[dict], dependencies=[Depends(cloud)])
def evaluate_model(
    model_id: str,
    body: EvaluateRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> dict:
    repo = MlModelRepo(session)
    model = repo.get(model_id)
    if model is None:
        raise ApiError(404, "not_found", "model not found")

    cache: ModelCache = request.app.state.model_cache
    cache.ensure(model.model_id, model.label_map, warm_up=False)
    s3 = S3ClipGateway(settings.s3_bucket, settings.aws_region, settings.aws_endpoint)
    evaluator = ModelEvaluator(s3_get=s3.get_bytes, runner=cache.runner)

    started = datetime.now(UTC)
    metrics = evaluator.evaluate(body.dataset, model.label_map)
    finished = datetime.now(UTC)

    repo.add_evaluation(
        model_id=model.model_id,
        dataset=body.dataset,
        metrics=metrics,
        started_at=started,
        finished_at=finished,
        created_by=SYSTEM_UUID,
    )
    repo.set_metrics(model, summary(metrics))
    session.commit()
    return data_response(metrics)


@router.post(
    "/{model_id}/activate", response_model=Envelope[ModelSummary], dependencies=[Depends(cloud)]
)
def activate_model(
    model_id: str,
    body: ActivateRequest,
    principal: Principal = Depends(cloud),
    session: Session = Depends(get_session),
    class_names: list[str] = Depends(get_class_names),
) -> dict:
    reg = _registry(session, class_names)
    model = reg.activate(model_id, activated_by=principal.sub)
    session.commit()
    return data_response(_summary(model))


@router.post(
    "/{model_id}/retire", response_model=Envelope[ModelSummary], dependencies=[Depends(cloud)]
)
def retire_model(
    model_id: str,
    session: Session = Depends(get_session),
    class_names: list[str] = Depends(get_class_names),
) -> dict:
    reg = _registry(session, class_names)
    model = reg.retire(model_id)
    session.commit()
    return data_response(_summary(model))
