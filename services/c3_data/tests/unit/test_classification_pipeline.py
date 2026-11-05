"""C3-05/06: persisting ClassificationPipeline (dedupe, upsert, mark analyzed, handoff)."""

from __future__ import annotations

import app.services.classification_pipeline as pipe
import pytest
from app.ml.label_mapper import LabelResult
from app.services.classification_pipeline import (
    ClassificationPipeline,
    ClassificationResult,
    DetectionExistsError,
    build_detection_document,
)

EV = {
    "_id": "media-1",
    "tenant_id": "t1",
    "house_id": "h1",
    "room_id": "r1",
    "s3": {"key": "tenants/t1/clip.wav"},
    "attempts": 1,
}
MODEL = {"model_id": "m1", "name": "yamnet", "version": "1.0.0", "label_map": {"entries": []}}


class _FakeDetections:
    """Contract-faithful fake: reproduces Mongo's _id immutability on replace.

    Pinned to real behavior by tests/contract/test_detection_repo_contract.py (Tier 3).
    """

    def __init__(self, existing=False, stored=None):
        self._stored = stored
        self.upserted: list[dict] = []
        # A prior detection exists for EV's media_id when existing/stored is set.
        self._by_media: dict[str, dict] = {}
        if stored is not None:
            self._by_media[stored["media_id"]] = stored
        elif existing:
            self._by_media["media-1"] = {"_id": "pre-existing", "media_id": "media-1"}

    def exists_for_media(self, media_id):
        return media_id in self._by_media

    def get_by_media(self, media_id):
        return self._by_media.get(media_id)

    def upsert_by_media(self, detection):
        existing = self._by_media.get(detection["media_id"])
        if existing is not None:
            detection["_id"] = existing["_id"]  # Mongo: _id is immutable on replace
        self._by_media[detection["media_id"]] = detection
        self.upserted.append(detection)


class _FakeEvents:
    def __init__(self):
        self.analyzed: list[tuple] = []

    def mark_analyzed(self, media_id, detection_id, handoff_status):
        self.analyzed.append((media_id, detection_id, handoff_status))


def _result(top="glass_break", conf=0.78):
    labels = [LabelResult(top, conf, "Glass", 2.9, 4.8)] if top != "none" else []
    return ClassificationResult(
        labels=labels,
        top_label=top,
        top_confidence=conf,
        raw_top10=[],
        frames=10,
        duration_s=5.0,
        latency_ms=33,
    )


def _pipeline(monkeypatch, detections, events, result, on_detection=None):
    monkeypatch.setattr(pipe, "classify_bytes", lambda *a, **k: result)
    return ClassificationPipeline(
        s3_get=lambda key: b"bytes",
        detection_repo=detections,
        media_event_repo=events,
        on_detection=on_detection,
    )


def test_build_detection_document_shape():
    doc = build_detection_document(EV, MODEL, _result())
    assert doc["media_id"] == "media-1"
    assert doc["model"] == {"model_id": "m1", "name": "yamnet", "version": "1.0.0"}
    assert doc["top_label"] == "glass_break"
    assert doc["labels"][0]["source_class"] == "Glass"
    assert "detected_at" in doc and doc["_id"]


def test_classify_persists_and_marks_analyzed(monkeypatch):
    det, ev = _FakeDetections(), _FakeEvents()
    p = _pipeline(monkeypatch, det, ev, _result())
    out = p.classify(EV, MODEL, object(), object(), MODEL["label_map"])
    assert len(det.upserted) == 1
    assert ev.analyzed == [("media-1", out["_id"], "done")]  # default log handoff -> done


def test_classify_dedupes_without_force(monkeypatch):
    det, ev = _FakeDetections(existing=True), _FakeEvents()
    p = _pipeline(monkeypatch, det, ev, _result())
    with pytest.raises(DetectionExistsError):
        p.classify(EV, MODEL, object(), object(), MODEL["label_map"])
    assert det.upserted == []
    assert ev.analyzed == []


def test_classify_force_replaces_existing(monkeypatch):
    det, ev = _FakeDetections(existing=True), _FakeEvents()
    p = _pipeline(monkeypatch, det, ev, _result())
    p.classify(EV, MODEL, object(), object(), MODEL["label_map"], force=True)
    assert len(det.upserted) == 1


def test_handoff_pending_status_is_recorded(monkeypatch):
    det, ev = _FakeDetections(), _FakeEvents()
    p = _pipeline(monkeypatch, det, ev, _result(), on_detection=lambda d: "pending")
    out = p.classify(EV, MODEL, object(), object(), MODEL["label_map"])
    assert ev.analyzed == [("media-1", out["_id"], "pending")]


def test_finish_existing_hands_off_and_marks_analyzed(monkeypatch):
    stored = {"_id": "det-1", "media_id": "media-1", "top_label": "glass_break"}
    det, ev, sent = _FakeDetections(existing=True, stored=stored), _FakeEvents(), []
    p = _pipeline(monkeypatch, det, ev, _result(), on_detection=lambda d: sent.append(d) or "done")
    assert p.finish_existing(EV) is stored
    assert sent == [stored]  # same detection_id again: C2 answers duplicate
    assert ev.analyzed == [("media-1", "det-1", "done")]
    assert det.upserted == []


def test_finish_existing_without_a_detection_does_nothing(monkeypatch):
    det, ev = _FakeDetections(), _FakeEvents()
    p = _pipeline(monkeypatch, det, ev, _result(), on_detection=lambda d: pytest.fail("sent"))
    assert p.finish_existing(EV) is None
    assert ev.analyzed == []
