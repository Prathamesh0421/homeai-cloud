"""Tier 2: the persisting pipeline + worker paths against real Mongo + LocalStack S3.

This is the test that would have caught the ``_id`` immutability bug (Phase 5's fake repo hid
it). The inference core (classify_bytes) is stubbed so these stay fast and store-focused; real
YAMNet is the separate ``slow`` tier. Covers the edge-case matrix rows that touch the store:
normal, force re-classify (stable detection_id), crash-after-step-6 resume via finish_existing,
handoff pending, unreadable clip, mark_failure at attempts==3, and a two-worker single claim.
"""

from __future__ import annotations

import uuid

import app.services.classification_pipeline as pipe
import pytest
from app.ml.audio import UnreadableClipError
from app.ml.label_mapper import LabelResult
from app.repositories.detection_repo import DetectionRepo
from app.repositories.media_event_repo import MediaEventRepo
from app.services.classification_pipeline import (
    ClassificationPipeline,
    ClassificationResult,
    DetectionExistsError,
)

pytestmark = pytest.mark.integration


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


@pytest.fixture
def stores(mongo_db, s3_bucket):
    client, bucket = s3_bucket
    detections = DetectionRepo(mongo_db["ai_detections"])
    events = MediaEventRepo(mongo_db["media_events"])
    return detections, events, client, bucket


def _put_clip(client, bucket, key: str) -> None:
    client.put_object(Bucket=bucket, Key=key, Body=b"RIFF....fake-wav-bytes")


def _insert_event(events: MediaEventRepo, bucket: str, key: str, status="queued", attempts=0):
    media_id = str(uuid.uuid4())
    events.collection.insert_one(
        {
            "_id": media_id,
            "tenant_id": "t1",
            "house_id": "h1",
            "room_id": "r1",
            "feed_id": "f1",
            "media_kind": "audio",
            "s3": {"bucket": bucket, "key": key},
            "uploaded_at": __import__("datetime").datetime.now(__import__("datetime").UTC),
            "status": status,
            "attempts": attempts,
            "handoff_status": "none",
        }
    )
    return media_id


MODEL = {"model_id": "m1", "name": "yamnet", "version": "1.0.0"}
LM = {"version": "1.0.0", "entries": []}


def _pipeline(detections, events, client, bucket, monkeypatch, result=None, handoff=None):
    monkeypatch.setattr(pipe, "classify_bytes", lambda *a, **k: result or _result())
    return ClassificationPipeline(
        s3_get=lambda key: client.get_object(Bucket=bucket, Key=key)["Body"].read(),
        detection_repo=detections,
        media_event_repo=events,
        on_detection=handoff or (lambda d: "done"),
    )


def test_normal_clip_one_detection_analyzed(stores, monkeypatch):
    det, ev, client, bucket = stores
    _put_clip(client, bucket, "k1.wav")
    mid = _insert_event(ev, bucket, "k1.wav")
    p = _pipeline(det, ev, client, bucket, monkeypatch)

    claimed = ev.claim_next("w1")
    p.classify(claimed, MODEL, object(), object(), LM)

    stored = list(det.collection.find({"media_id": mid}))
    assert len(stored) == 1
    assert ev.get(mid)["status"] == "analyzed"
    assert ev.get(mid)["handoff_status"] == "done"


def test_force_reclassify_keeps_detection_id(stores, monkeypatch):
    det, ev, client, bucket = stores
    _put_clip(client, bucket, "k2.wav")
    mid = _insert_event(ev, bucket, "k2.wav")

    p1 = _pipeline(det, ev, client, bucket, monkeypatch, result=_result("speech", 0.6))
    first = p1.classify(ev.claim_next("w1"), MODEL, object(), object(), LM)
    first_id = first["_id"]

    # Re-classify with force: new label, SAME detection_id (idempotency contract, section 8).
    p2 = _pipeline(det, ev, client, bucket, monkeypatch, result=_result("glass_break", 0.8))
    again = p2.classify(ev.get(mid), MODEL, object(), object(), LM, force=True)

    stored = list(det.collection.find({"media_id": mid}))
    assert len(stored) == 1
    assert stored[0]["_id"] == first_id  # unchanged -> C2 sees duplicate, no second alert
    assert again["_id"] == first_id
    assert stored[0]["top_label"] == "glass_break"


def test_dedupe_without_force_raises(stores, monkeypatch):
    det, ev, client, bucket = stores
    _put_clip(client, bucket, "k3.wav")
    mid = _insert_event(ev, bucket, "k3.wav")
    p = _pipeline(det, ev, client, bucket, monkeypatch)
    p.classify(ev.claim_next("w1"), MODEL, object(), object(), LM)
    with pytest.raises(DetectionExistsError):
        p.classify(ev.get(mid), MODEL, object(), object(), LM)


def test_crash_after_step6_resume_via_finish_existing(stores, monkeypatch):
    """Detection stored but clip never marked analyzed -> finish_existing completes it."""
    det, ev, client, bucket = stores
    _put_clip(client, bucket, "k4.wav")
    mid = _insert_event(ev, bucket, "k4.wav")

    # Simulate a crash after step 6: store the detection, but leave the clip 'processing'.
    detection = {
        "_id": str(uuid.uuid4()),
        "media_id": mid,
        "tenant_id": "t1",
        "house_id": "h1",
        "room_id": "r1",
        "model": MODEL,
        "labels": [],
        "top_label": "none",
        "top_confidence": 0.0,
        "detected_at": __import__("datetime").datetime.now(__import__("datetime").UTC),
    }
    det.upsert_by_media(detection)
    ev.collection.update_one({"_id": mid}, {"$set": {"status": "processing"}})

    handoffs: list[str] = []
    p = _pipeline(
        det, ev, client, bucket, monkeypatch, handoff=lambda d: handoffs.append(d["_id"]) or "done"
    )
    out = p.finish_existing(ev.get(mid))
    assert out["_id"] == detection["_id"]
    assert ev.get(mid)["status"] == "analyzed"
    assert handoffs == [detection["_id"]]  # handoff re-sent with the stored id


def test_handoff_pending_recorded(stores, monkeypatch):
    det, ev, client, bucket = stores
    _put_clip(client, bucket, "k5.wav")
    mid = _insert_event(ev, bucket, "k5.wav")
    p = _pipeline(det, ev, client, bucket, monkeypatch, handoff=lambda d: "pending")
    p.classify(ev.claim_next("w1"), MODEL, object(), object(), LM)
    assert ev.get(mid)["handoff_status"] == "pending"


def test_unreadable_clip_raises(stores, monkeypatch):
    det, ev, client, bucket = stores
    _put_clip(client, bucket, "k6.wav")
    mid = _insert_event(ev, bucket, "k6.wav")
    monkeypatch.setattr(
        pipe, "classify_bytes", lambda *a, **k: (_ for _ in ()).throw(UnreadableClipError("bad"))
    )
    p = ClassificationPipeline(
        s3_get=lambda key: b"x",
        detection_repo=det,
        media_event_repo=ev,
        on_detection=lambda d: "done",
    )
    with pytest.raises(UnreadableClipError):
        p.classify(ev.claim_next("w1"), MODEL, object(), object(), LM)
    assert det.get_by_media(mid) is None  # nothing persisted


def test_two_workers_single_claim(stores):
    _det, ev, client, bucket = stores
    _put_clip(client, bucket, "k7.wav")
    _insert_event(ev, bucket, "k7.wav")
    a = ev.claim_next("w1")
    b = ev.claim_next("w2")
    assert a is not None
    assert b is None  # the single queued clip was claimed exactly once


def test_mark_failure_at_three_attempts_is_failed(stores):
    _det, ev, _client, bucket = stores
    mid = _insert_event(ev, bucket, "k8.wav", status="processing", attempts=3)
    assert ev.mark_failure(mid, attempts=3, error="boom") == "failed"
    assert ev.get(mid)["status"] == "failed"
