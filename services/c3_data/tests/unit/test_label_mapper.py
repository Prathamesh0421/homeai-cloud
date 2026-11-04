"""C3-04: label mapper rules (max/mean/consec2), thresholds, sorting, validation."""

from __future__ import annotations

import numpy as np
import pytest
from app.ml.label_mapper import LabelMapper, LabelMapValidationError, validate_label_map

# A tiny synthetic class universe; indices are positions in this list.
CLASSES = ["Glass", "Shatter", "Speech", "Conversation", "Thump, thud", "Bang", "Dog", "Bark"]


def _mapper() -> LabelMapper:
    return LabelMapper(CLASSES)


def _scores(col_values: dict[int, list[float]], n_frames: int) -> np.ndarray:
    """Build an (n_frames, len(CLASSES)) matrix; unspecified columns are zero."""
    m = np.zeros((n_frames, len(CLASSES)), dtype=np.float32)
    for col, vals in col_values.items():
        m[:, col] = vals
    return m


def _entry(home_label, source_classes, min_confidence, rule):
    return {
        "home_label": home_label,
        "source_classes": source_classes,
        "min_confidence": min_confidence,
        "rule": rule,
    }


def test_max_rule_detects_at_peak_frame():
    scores = _scores({0: [0.3, 0.7, 0.2]}, 3)  # "Glass"
    lm = {"entries": [_entry("glass_break", ["Glass"], 0.55, "max")]}
    res = _mapper().apply(scores, lm)
    assert len(res) == 1
    assert res[0].label == "glass_break"
    assert res[0].confidence == pytest.approx(0.7, abs=1e-4)
    assert res[0].source_class == "Glass"


def test_mean_rule():
    scores = _scores({2: [0.6, 0.4, 0.5]}, 3)  # "Speech"
    lm = {"entries": [_entry("speech", ["Speech"], 0.50, "mean")]}
    res = _mapper().apply(scores, lm)
    assert len(res) == 1
    assert res[0].confidence == pytest.approx(0.5, abs=1e-4)


def test_consec2_rule():
    scores = _scores({4: [0.3, 0.7, 0.8, 0.2]}, 4)  # "Thump, thud"
    lm = {"entries": [_entry("fall_indicator", ["Thump, thud"], 0.60, "consec2")]}
    res = _mapper().apply(scores, lm)
    assert len(res) == 1
    assert res[0].confidence == pytest.approx(0.7, abs=1e-4)  # min(0.7, 0.8)


def test_consec2_single_frame_is_that_frame():
    scores = _scores({4: [0.9]}, 1)
    lm = {"entries": [_entry("fall_indicator", ["Thump, thud"], 0.60, "consec2")]}
    res = _mapper().apply(scores, lm)
    assert len(res) == 1
    assert res[0].confidence == pytest.approx(0.9, abs=1e-4)


def test_below_threshold_returns_empty():
    scores = _scores({0: [0.1, 0.2, 0.1]}, 3)
    lm = {"entries": [_entry("glass_break", ["Glass"], 0.55, "max")]}
    assert _mapper().apply(scores, lm) == []


def test_multiple_labels_sorted_by_confidence_desc():
    scores = _scores({0: [0.6, 0.6, 0.6], 6: [0.9, 0.9, 0.9]}, 3)  # Glass + Dog
    lm = {
        "entries": [
            _entry("glass_break", ["Glass"], 0.50, "max"),
            _entry("dog", ["Dog"], 0.50, "max"),
        ]
    }
    res = _mapper().apply(scores, lm)
    assert [r.label for r in res] == ["dog", "glass_break"]
    assert res[0].confidence >= res[1].confidence


def test_source_class_is_best_scoring_member():
    # Entry has two source classes; Shatter scores higher than Glass in the peak frame.
    scores = _scores({0: [0.3, 0.3], 1: [0.4, 0.8]}, 2)
    lm = {"entries": [_entry("glass_break", ["Glass", "Shatter"], 0.55, "max")]}
    res = _mapper().apply(scores, lm)
    assert res[0].source_class == "Shatter"


def test_empty_score_matrix_returns_empty():
    scores = np.zeros((0, len(CLASSES)), dtype=np.float32)
    lm = {"entries": [_entry("glass_break", ["Glass"], 0.55, "max")]}
    assert _mapper().apply(scores, lm) == []


def test_validate_label_map_ok():
    lm = {"entries": [_entry("glass_break", ["Glass", "Shatter"], 0.55, "max")]}
    validate_label_map(lm, CLASSES)  # no raise


def test_validate_label_map_reports_unknown_class():
    lm = {"entries": [_entry("x", ["Glass", "Nonexistent Class"], 0.5, "max")]}
    with pytest.raises(LabelMapValidationError) as exc:
        validate_label_map(lm, CLASSES)
    assert "Nonexistent Class" in exc.value.unknown
