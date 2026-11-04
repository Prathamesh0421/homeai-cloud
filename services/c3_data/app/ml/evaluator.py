"""Model evaluation on a labelled dataset (C3-08, docs §4.4).

Runs the inference core (decode -> YAMNet -> label map) over each clip in an eval manifest
(``models/eval/{dataset}/manifest.json``: ``[{"file","expected"}, ...]``), comparing the
predicted top label (or ``"none"``) to the expected label. Computes accuracy, per-label
precision/recall/F1/support, an 8x8 confusion matrix (7 home labels + ``none``), and latency.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np

from app.ml.label_mapper import LabelMapper
from app.ml.yamnet_runner import YamnetRunner
from app.services.classification_pipeline import classify_bytes

# The 7 home labels plus "none" — the full confusion-matrix universe (docs §2.3).
LABELS = [
    "smoke_alarm",
    "distress_sound",
    "glass_break",
    "fall_indicator",
    "cough",
    "speech",
    "dog",
    "none",
]


@dataclass
class EvalItem:
    file: str
    expected: str


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    return int(np.percentile(np.array(values), 95))


def compute_metrics(
    pairs: list[tuple[str, str]], latencies_ms: list[int], dataset: str
) -> dict[str, Any]:
    """From (expected, predicted) pairs, compute accuracy/PRF1/confusion/latency."""
    index = {label: i for i, label in enumerate(LABELS)}
    n = len(LABELS)
    confusion = [[0] * n for _ in range(n)]
    correct = 0
    for expected, predicted in pairs:
        ei, pi = index.get(expected, index["none"]), index.get(predicted, index["none"])
        confusion[ei][pi] += 1
        if ei == pi:
            correct += 1

    total = len(pairs)
    per_label: dict[str, dict[str, float]] = {}
    for label in LABELS:
        i = index[label]
        tp = confusion[i][i]
        support = sum(confusion[i])  # actual positives
        predicted_pos = sum(confusion[r][i] for r in range(n))
        precision = tp / predicted_pos if predicted_pos else 0.0
        recall = tp / support if support else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        per_label[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
        }

    macro_f1 = round(sum(v["f1"] for v in per_label.values()) / n, 4)
    avg_latency = int(sum(latencies_ms) / len(latencies_ms)) if latencies_ms else 0
    return {
        "dataset": dataset,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "macro_f1": macro_f1,
        "per_label": per_label,
        "labels": LABELS,
        "confusion": confusion,
        "avg_latency_ms": avg_latency,
        "p95_latency_ms": _p95(latencies_ms),
        "n_clips": total,
        "evaluated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


class ModelEvaluator:
    def __init__(self, *, s3_get: Callable[[str], bytes], runner: YamnetRunner):
        self._s3_get = s3_get
        self._runner = runner

    def _manifest(self, dataset: str) -> list[EvalItem]:
        raw = self._s3_get(f"models/eval/{dataset}/manifest.json")
        data = json.loads(raw)
        return [EvalItem(file=d["file"], expected=d["expected"]) for d in data]

    def evaluate(self, dataset: str, label_map: dict[str, Any]) -> dict[str, Any]:
        mapper = LabelMapper(self._runner.class_names)
        items = self._manifest(dataset)
        pairs: list[tuple[str, str]] = []
        latencies: list[int] = []
        for item in items:
            raw = self._s3_get(f"models/eval/{dataset}/{item.file}")
            start = time.perf_counter()
            result = classify_bytes(raw, self._runner, mapper, label_map)
            latencies.append(int((time.perf_counter() - start) * 1000))
            pairs.append((item.expected, result.top_label))
        return compute_metrics(pairs, latencies, dataset)


def summary(metrics: dict[str, Any]) -> dict[str, Any]:
    """Small summary copied to ml_models.metrics for the list view."""
    return {
        "dataset": metrics.get("dataset"),
        "accuracy": metrics.get("accuracy"),
        "macro_f1": metrics.get("macro_f1"),
        "evaluated_at": metrics.get("evaluated_at"),
    }
