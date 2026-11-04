"""C3-05: POST /inference/test HTTP behavior (auth, 404/413/422, happy-path shape).

The ML core (classify_bytes) is stubbed so these fast tests need neither TensorFlow nor ffmpeg;
real YAMNet inference is covered by the slow tests on demo clips.
"""

from __future__ import annotations

import app.api.inference as inference_api
from app.api.deps import get_model_cache, get_session
from app.ml.audio import UnreadableClipError
from app.ml.label_mapper import LabelResult
from app.services.classification_pipeline import ClassificationResult, RawScore


class _FakeModel:
    def __init__(self, model_id="m1", name="yamnet", version="1.0.0"):
        self.model_id = model_id
        self.name = name
        self.version = version
        self.label_map = {"entries": []}


class _FakeRepoSession:
    """Stands in for a Session; the fake repo reads .model off it."""

    def __init__(self, model):
        self.model = model


def _install(app, model, classify_result=None, raise_unreadable=False, monkeypatch=None):
    # Override repo data source.
    def fake_session():
        yield _FakeRepoSession(model)

    app.dependency_overrides[get_session] = fake_session

    class _FakeCache:
        def ensure(self, *a, **k):
            return True

        runner = object()
        mapper = object()

    app.dependency_overrides[get_model_cache] = lambda: _FakeCache()

    # Patch the repo to use the session's .model, and the classify core.
    from app.repositories import ml_model_repo

    monkeypatch.setattr(
        ml_model_repo.MlModelRepo, "get", lambda self, mid: getattr(self.session, "model", None)
    )
    monkeypatch.setattr(
        ml_model_repo.MlModelRepo, "get_active", lambda self: getattr(self.session, "model", None)
    )

    def fake_classify(raw, runner, mapper, label_map):
        if raise_unreadable:
            raise UnreadableClipError("bad clip")
        return classify_result

    monkeypatch.setattr(inference_api, "classify_bytes", fake_classify)


def _cloud_header(auth_header):
    return auth_header(role="cloud_staff", tenant_id="t1")


def test_requires_auth(client):
    r = client.post("/api/v1/inference/test", files={"file": ("c.wav", b"x", "audio/wav")})
    assert r.status_code == 401


def test_rejected_for_house_owner(client, auth_header):
    h = auth_header(role="house_owner", tenant_id="t1", house_ids=["h1"])
    r = client.post(
        "/api/v1/inference/test", files={"file": ("c.wav", b"x", "audio/wav")}, headers=h
    )
    assert r.status_code == 403


def test_happy_path(client, auth_header, monkeypatch):
    result = ClassificationResult(
        labels=[LabelResult("glass_break", 0.78, "Glass", 2.88, 4.8)],
        top_label="glass_break",
        top_confidence=0.78,
        raw_top10=[RawScore("Glass", 0.78), RawScore("Shatter", 0.6)],
        frames=10,
        duration_s=5.0,
        latency_ms=42,
    )
    _install(client.app, _FakeModel(), classify_result=result, monkeypatch=monkeypatch)
    r = client.post(
        "/api/v1/inference/test",
        files={"file": ("glass.wav", b"RIFFdata", "audio/wav")},
        headers=_cloud_header(auth_header),
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["top_label"] == "glass_break"
    assert data["model"]["version"] == "1.0.0"
    assert data["labels"][0]["source_class"] == "Glass"
    assert data["raw_top10"][0]["class_name"] == "Glass"
    client.app.dependency_overrides.clear()


def test_unknown_model_id_is_404(client, auth_header, monkeypatch):
    _install(client.app, None, monkeypatch=monkeypatch)
    r = client.post(
        "/api/v1/inference/test",
        data={"model_id": "missing"},
        files={"file": ("c.wav", b"x", "audio/wav")},
        headers=_cloud_header(auth_header),
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    client.app.dependency_overrides.clear()


def test_unreadable_clip_is_422(client, auth_header, monkeypatch):
    _install(client.app, _FakeModel(), raise_unreadable=True, monkeypatch=monkeypatch)
    r = client.post(
        "/api/v1/inference/test",
        files={"file": ("c.bin", b"garbage", "application/octet-stream")},
        headers=_cloud_header(auth_header),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unreadable_clip"
    client.app.dependency_overrides.clear()
