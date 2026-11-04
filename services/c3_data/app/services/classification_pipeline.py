"""Classification pipeline (C3-05, docs §4.2).

Phase 4 implements the inference core (steps 2-5) used by ``POST /inference/test``:
decode audio -> run YAMNet -> apply the label map -> assemble labels + raw top-10.

The persisting worker path (steps 1, 6-8: dedupe, upsert ai_detections, set media_events,
activity rollup, C2 handoff) is wired up in Phase 5 (worker) and Phase 7 (handoff). The
``classify_bytes`` core here is what those phases reuse.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from app.ml.audio import decode_audio, duration_seconds
from app.ml.label_mapper import LabelMapper, LabelResult
from app.ml.yamnet_runner import YamnetRunner

RAW_TOP_N = 10


@dataclass
class RawScore:
    class_name: str
    score: float


@dataclass
class ClassificationResult:
    labels: list[LabelResult]
    top_label: str
    top_confidence: float
    raw_top10: list[RawScore]
    frames: int
    duration_s: float
    latency_ms: int
    extra: dict = field(default_factory=dict)


def _raw_top10(scores: np.ndarray, class_names: list[str]) -> list[RawScore]:
    """Top-10 YAMNet classes by max score over frames (for the Test Classify raw view)."""
    if scores.shape[0] == 0:
        return []
    per_class = scores.max(axis=0)  # best score per class across frames
    top_idx = np.argsort(per_class)[::-1][:RAW_TOP_N]
    return [RawScore(class_names[i], round(float(per_class[i]), 4)) for i in top_idx]


def classify_bytes(
    raw_bytes: bytes,
    runner: YamnetRunner,
    mapper: LabelMapper,
    label_map: dict,
) -> ClassificationResult:
    """Run the inference core on clip bytes. No persistence, no handoff.

    Raises ``UnreadableClipError`` (from decode_audio) on undecodable input.
    """
    start = time.perf_counter()

    waveform = decode_audio(raw_bytes)
    scores = runner.classify(waveform)
    labels = mapper.apply(scores, label_map)
    raw = _raw_top10(scores, runner.class_names)

    if labels:
        top = labels[0]
        top_label, top_confidence = top.label, top.confidence
    else:
        top_label, top_confidence = "none", 0.0

    latency_ms = int((time.perf_counter() - start) * 1000)
    return ClassificationResult(
        labels=labels,
        top_label=top_label,
        top_confidence=top_confidence,
        raw_top10=raw,
        frames=int(scores.shape[0]),
        duration_s=duration_seconds(waveform),
        latency_ms=latency_ms,
    )


class DetectionExistsError(Exception):
    """A detection already exists for this media_id and force was not set."""


def build_detection_document(ev: dict, model: dict, result: ClassificationResult) -> dict:
    """Assemble an ``ai_detections`` document (contract §4.2) from the event and result."""
    return {
        "_id": str(uuid.uuid4()),
        "media_id": ev["_id"],
        "tenant_id": ev["tenant_id"],
        "house_id": ev["house_id"],
        "room_id": ev.get("room_id"),
        "model": {
            "model_id": model["model_id"],
            "name": model["name"],
            "version": model["version"],
        },
        "labels": [
            {
                "label": label.label,
                "confidence": label.confidence,
                "source_class": label.source_class,
                "start_s": label.start_s,
                "end_s": label.end_s,
            }
            for label in result.labels
        ],
        "top_label": result.top_label,
        "top_confidence": result.top_confidence,
        "detected_at": datetime.now(UTC),
    }


class ClassificationPipeline:
    """Full persisting pipeline (docs §4.2 steps 1-8) used by the worker and classify endpoint.

    Dependencies are injected so the pipeline is testable without TF/S3/Mongo:
      s3_get(key) -> bytes, detection_repo, media_event_repo, model cache.
    ``on_detection`` is the C2 handoff hook (Phase 7); it returns the handoff_status string
    ("done"/"pending"); default logs and returns "done" (HANDOFF_MODE=log). ``on_rollup`` is the
    activity rollup hook (Phase 8); default is a no-op.
    """

    def __init__(
        self,
        *,
        s3_get: Callable[[str], bytes],
        detection_repo,
        media_event_repo,
        on_detection: Callable[[dict], str] | None = None,
        on_rollup: Callable[[dict], None] | None = None,
    ):
        self._s3_get = s3_get
        self._detections = detection_repo
        self._events = media_event_repo
        self._on_detection = on_detection or self._log_handoff
        self._on_rollup = on_rollup or (lambda _doc: None)

    @staticmethod
    def _log_handoff(detection: dict) -> str:
        import logging

        logging.getLogger("c3.handoff").info(
            "handoff (log mode)",
            extra={"detection_id": detection["_id"], "top_label": detection["top_label"]},
        )
        return "done"

    def classify(
        self,
        ev: dict,
        model: dict,
        runner: YamnetRunner,
        mapper: LabelMapper,
        label_map: dict,
        *,
        force: bool = False,
    ) -> dict:
        """Run steps 1-8 for a stored clip event; return the persisted detection document."""
        media_id = ev["_id"]

        # 1. Dedupe unless force.
        if not force and self._detections.exists_for_media(media_id):
            raise DetectionExistsError(media_id)

        # 2-5. Download + inference core.
        raw = self._s3_get(ev["s3"]["key"])
        result = classify_bytes(raw, runner, mapper, label_map)

        # 6. Build + upsert detection; mark the clip analyzed.
        detection = build_detection_document(ev, model, result)
        self._detections.upsert_by_media(detection)

        # 7. Activity rollup (Phase 8 hook).
        self._on_rollup(detection)

        # 8. Handoff to C2 (Phase 7 hook); record the resulting handoff status.
        handoff_status = self._on_detection(detection)
        self._events.mark_analyzed(media_id, detection["_id"], handoff_status)

        detection["_latency_ms"] = result.latency_ms
        return detection

    def finish_existing(self, ev: dict) -> dict | None:
        """Worker path for a clip whose detection is already stored but whose run never finished.

        An earlier attempt saved the detection (step 6) and then failed or crashed before the
        clip was marked analyzed, so it came back to the queue. Re-classifying would only hit
        the dedupe, so finish the run instead: hand off to C2 again (idempotent on
        ``detection_id``, so a repeat is safe) and mark the clip analyzed. The activity rollup
        is not repeated. Returns the stored detection, or None if there is none.
        """
        detection = self._detections.get_by_media(ev["_id"])
        if detection is None:
            return None
        handoff_status = self._on_detection(detection)
        self._events.mark_analyzed(ev["_id"], detection["_id"], handoff_status)
        return detection
