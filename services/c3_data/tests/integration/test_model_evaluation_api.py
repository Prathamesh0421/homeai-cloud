"""C3-08 model evaluation/activation regression tests on real Postgres."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.api import models as models_api
from app.api.deps import get_mongo, get_session
from app.models.orm import MlModel
from sqlalchemy import text

pytestmark = pytest.mark.integration


class _EmptyCollection:
    def count_documents(self, _query):
        return 0

    def find(self, _query):
        return []


class _EmptyMongo:
    def __getitem__(self, _name):
        return _EmptyCollection()


class _FakeCache:
    runner = object()

    def ensure(self, _model_id, _label_map, *, warm_up):
        assert warm_up is False


class _FakeEvaluator:
    def __init__(self, *, s3_get, runner):
        assert callable(s3_get)
        assert runner is _FakeCache.runner

    def evaluate(self, dataset, _label_map):
        return {
            "dataset": dataset,
            "accuracy": 1.0,
            "macro_f1": 1.0,
            "evaluated_at": "2026-11-11T12:00:00Z",
        }


LABEL_MAP = {
    "version": "9.0.0",
    "entries": [
        {
            "home_label": "glass_break",
            "source_classes": ["Glass"],
            "min_confidence": 0.5,
            "rule": "max",
        }
    ],
}


def _clear_models(session):
    session.execute(text("DELETE FROM c3.model_evaluations"))
    session.execute(text("DELETE FROM c3.ml_models"))
    session.commit()


def test_evaluate_active_model_keeps_deployment_and_original_flow_works(
    pg_session, make_client, auth_header, monkeypatch
):
    """registered -> evaluated -> active, then re-evaluate without demoting it."""
    _clear_models(pg_session)
    original = MlModel(
        name="yamnet",
        version="9.0.0",
        source="bundled",
        label_map=LABEL_MAP,
        status="active",
        created_by="00000000-0000-0000-0000-000000000000",
    )
    pg_session.add(original)
    pg_session.commit()

    client = make_client()
    client.app.dependency_overrides[get_session] = lambda: pg_session
    client.app.dependency_overrides[get_mongo] = lambda: _EmptyMongo()
    client.app.state.class_names = ["Glass"]
    client.app.state.model_cache = _FakeCache()
    monkeypatch.setattr(
        models_api,
        "S3ClipGateway",
        lambda *_args, **_kwargs: SimpleNamespace(get_bytes=lambda _key: b""),
    )
    monkeypatch.setattr(models_api, "ModelEvaluator", _FakeEvaluator)
    headers = auth_header(role="cloud_staff")

    try:
        created = client.post(
            "/api/v1/models",
            json={"version": "9.1.0", "base_model_id": original.model_id},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        candidate_id = created.json()["data"]["model_id"]
        assert created.json()["data"]["status"] == "registered"

        evaluated = client.post(
            f"/api/v1/models/{candidate_id}/evaluate",
            json={"dataset": "eval-v1"},
            headers=headers,
        )
        assert evaluated.status_code == 200, evaluated.text
        detail = client.get(f"/api/v1/models/{candidate_id}", headers=headers)
        assert detail.json()["data"]["status"] == "evaluated"

        activated = client.post(
            f"/api/v1/models/{candidate_id}/activate",
            json={"confirm": True},
            headers=headers,
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["data"]["status"] == "active"
        pg_session.refresh(original)
        assert original.status == "retired"

        reevaluated = client.post(
            f"/api/v1/models/{candidate_id}/evaluate",
            json={"dataset": "eval-v1"},
            headers=headers,
        )
        assert reevaluated.status_code == 200, reevaluated.text

        active_count = pg_session.execute(
            text("SELECT count(*) FROM c3.ml_models WHERE status='active'")
        ).scalar_one()
        assert active_count == 1

        deployment = client.get("/api/v1/models/deployment", headers=headers)
        assert deployment.status_code == 200, deployment.text
        assert deployment.json()["data"]["active_model"] == {
            "id": candidate_id,
            "version": "9.1.0",
        }

        detail = client.get(f"/api/v1/models/{candidate_id}", headers=headers)
        assert detail.json()["data"]["status"] == "active"
        assert detail.json()["data"]["metrics"]["accuracy"] == 1.0
    finally:
        client.app.dependency_overrides.clear()
        _clear_models(pg_session)
