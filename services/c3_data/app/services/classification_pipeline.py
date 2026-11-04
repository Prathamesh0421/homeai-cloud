"""Classification pipeline (C3-05, docs §4.2).

Phase 4 implements the inference core (steps 2-5) used by ``POST /inference/test``:
decode audio -> run YAMNet -> apply the label map -> assemble labels + raw top-10.

The persisting worker path (steps 1, 6-8: dedupe, upsert ai_detections, set media_events,
activity rollup, C2 handoff) is wired up in Phase 5 (worker) and Phase 7 (handoff). The
``classify_bytes`` core here is what those phases reuse.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

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
