"""Map YAMNet's 521-class scores to home labels (C3-04, docs §4.2 step 4, §2.3).

Pure numpy: given the per-frame score matrix ``(frames, 521)`` and a label map, produce the
home-label detections. Three per-entry aggregation rules:

  max      -> max over frames of the per-frame score
  mean     -> mean over frames
  consec2  -> max over i of min(per_frame[i], per_frame[i+1])  (single frame -> that frame)

``per_frame`` for an entry is, per frame, the max score across the entry's source classes.
An entry is kept when its aggregated confidence >= ``min_confidence``; results are sorted by
confidence descending. ``validate_label_map`` checks every source class exists in YAMNet's list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.ml.yamnet_runner import FRAME_HOP_SECONDS, FRAME_WINDOW_SECONDS

VALID_RULES = {"max", "mean", "consec2"}


@dataclass(frozen=True)
class LabelResult:
    label: str
    confidence: float
    source_class: str
    start_s: float
    end_s: float


class LabelMapValidationError(Exception):
    """Raised when a label map references YAMNet classes that do not exist."""

    def __init__(self, unknown: list[str]):
        self.unknown = unknown
        super().__init__(f"unknown source classes: {unknown}")


def validate_label_map(label_map: dict[str, Any], class_names: list[str]) -> None:
    """Raise ``LabelMapValidationError`` listing any source class not in ``class_names``."""
    known = set(class_names)
    unknown: list[str] = []
    for entry in label_map.get("entries", []):
        for src in entry.get("source_classes", []):
            if src not in known:
                unknown.append(src)
    if unknown:
        # De-duplicate while preserving order.
        raise LabelMapValidationError(list(dict.fromkeys(unknown)))


def _frame_time(index: int) -> tuple[float, float]:
    start = round(FRAME_HOP_SECONDS * index, 3)
    end = round(FRAME_HOP_SECONDS * index + FRAME_WINDOW_SECONDS, 3)
    return start, end


class LabelMapper:
    """Applies a label map to a YAMNet score matrix."""

    def __init__(self, class_names: list[str]):
        self.class_names = class_names
        self._index = {name: i for i, name in enumerate(class_names)}

    def _source_indices(self, source_classes: list[str]) -> list[int]:
        return [self._index[c] for c in source_classes if c in self._index]

    def apply(self, scores: np.ndarray, label_map: dict[str, Any]) -> list[LabelResult]:
        """Return the home labels that pass their threshold, sorted by confidence desc."""
        results: list[LabelResult] = []
        n_frames = scores.shape[0]
        if n_frames == 0:
            return results

        for entry in label_map.get("entries", []):
            idxs = self._source_indices(entry.get("source_classes", []))
            if not idxs:
                continue
            rule = entry.get("rule", "max")
            threshold = float(entry.get("min_confidence", 1.0))

            # per_frame[f] = best source-class score in that frame.
            sub = scores[:, idxs]  # (frames, k)
            per_frame = sub.max(axis=1)  # (frames,)
            # Which source class drove each frame (for reporting source_class at the best frame).
            best_src_col = sub.argmax(axis=1)

            confidence, best_frame = self._aggregate(rule, per_frame)
            if confidence < threshold:
                continue

            source_class = entry["source_classes"][int(best_src_col[best_frame])]
            if rule == "consec2" and n_frames >= 2 and best_frame < n_frames - 1:
                start_s, _ = _frame_time(best_frame)
                _, end_s = _frame_time(best_frame + 1)
            else:
                start_s, end_s = _frame_time(best_frame)

            results.append(
                LabelResult(
                    label=entry["home_label"],
                    confidence=round(float(confidence), 4),
                    source_class=source_class,
                    start_s=start_s,
                    end_s=end_s,
                )
            )

        results.sort(key=lambda r: r.confidence, reverse=True)
        return results

    @staticmethod
    def _aggregate(rule: str, per_frame: np.ndarray) -> tuple[float, int]:
        """Return (confidence, index_of_best_frame) for the rule."""
        if rule == "mean":
            return float(per_frame.mean()), int(per_frame.argmax())
        if rule == "consec2":
            if len(per_frame) == 1:
                return float(per_frame[0]), 0
            pair_min = np.minimum(per_frame[:-1], per_frame[1:])  # min of each adjacent pair
            i = int(pair_min.argmax())
            return float(pair_min[i]), i
        # default: max
        i = int(per_frame.argmax())
        return float(per_frame[i]), i
