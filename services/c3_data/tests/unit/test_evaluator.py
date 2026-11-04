"""C3-08: evaluator metrics (accuracy, precision/recall/F1, confusion) on fixed pairs."""

from __future__ import annotations

from app.ml.evaluator import LABELS, compute_metrics


def test_perfect_predictions():
    pairs = [("glass_break", "glass_break"), ("dog", "dog"), ("none", "none")]
    m = compute_metrics(pairs, [10, 20, 30], "eval-v1")
    assert m["accuracy"] == 1.0
    assert m["per_label"]["glass_break"]["f1"] == 1.0
    assert m["avg_latency_ms"] == 20
    assert m["n_clips"] == 3


def test_confusion_and_prf1():
    # glass_break predicted as none once (a miss), dog correct twice.
    pairs = [
        ("glass_break", "none"),
        ("dog", "dog"),
        ("dog", "dog"),
    ]
    m = compute_metrics(pairs, [5, 5, 5], "eval-v1")
    assert m["accuracy"] == round(2 / 3, 4)
    # glass_break: support 1, recall 0 (missed).
    assert m["per_label"]["glass_break"]["recall"] == 0.0
    assert m["per_label"]["glass_break"]["support"] == 1
    # dog: perfect.
    assert m["per_label"]["dog"]["precision"] == 1.0
    assert m["per_label"]["dog"]["recall"] == 1.0
    # confusion is len(LABELS) x len(LABELS).
    assert len(m["confusion"]) == len(LABELS)
    assert all(len(row) == len(LABELS) for row in m["confusion"])
    gi, ni = LABELS.index("glass_break"), LABELS.index("none")
    assert m["confusion"][gi][ni] == 1  # glass_break actual, none predicted


def test_empty_dataset():
    m = compute_metrics([], [], "eval-v1")
    assert m["accuracy"] == 0.0
    assert m["n_clips"] == 0
