"""YAMNet SavedModel runner (C3-03, docs §5).

Loads the bundled YAMNet SavedModel (``hub.load(model_dir)``), exposes the 521 class display
names, and runs inference returning the per-frame score matrix of shape ``(frames, 521)``.

TensorFlow and tensorflow_hub are imported lazily so modules that only need the class list or
the pure label-mapping logic do not pay the heavy import cost (and tests can run without TF).
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

# Each YAMNet frame covers 0.96 s and hops 0.48 s (docs §4.2 step 3).
FRAME_HOP_SECONDS = 0.48
FRAME_WINDOW_SECONDS = 0.96
NUM_CLASSES = 521


def load_class_names(class_map_csv: str | Path) -> list[str]:
    """Read YAMNet display names from the class map CSV (columns: index, mid, display_name)."""
    names: list[str] = []
    with open(class_map_csv, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        # The official file has a header row "index,mid,display_name"; tolerate its absence.
        if header and header[0].strip().lower() not in {"index", "idx"}:
            names.append(header[2] if len(header) >= 3 else header[-1])
        for row in reader:
            if row:
                names.append(row[2] if len(row) >= 3 else row[-1])
    return names


class YamnetRunner:
    """Wraps a loaded YAMNet SavedModel. Load once per process; reuse across clips."""

    # Relative location of the bundled YAMNet SavedModel under the configured model dir
    # (matches scripts/download_yamnet.py, which writes to <model_dir>/yamnet/1).
    BUNDLED_SUBPATH = Path("yamnet") / "1"

    def __init__(self, model_dir: str | Path):
        # Accept either the parent dir (/models) or a direct SavedModel dir (/models/yamnet/1).
        self.model_dir = self._resolve_saved_model_dir(Path(model_dir))
        self._model = None
        self._class_names: list[str] | None = None

    @classmethod
    def _resolve_saved_model_dir(cls, path: Path) -> Path:
        if (path / "saved_model.pb").exists():
            return path
        bundled = path / cls.BUNDLED_SUBPATH
        if (bundled / "saved_model.pb").exists():
            return bundled
        # Fall back to the bundled subpath so an error message points at the expected layout.
        return bundled

    def load(self) -> None:
        import tensorflow_hub as hub

        self._model = hub.load(str(self.model_dir))
        class_map_path = self._resolve_class_map()
        self._class_names = load_class_names(class_map_path)
        if len(self._class_names) != NUM_CLASSES:
            raise ValueError(f"expected {NUM_CLASSES} YAMNet classes, got {len(self._class_names)}")

    def _resolve_class_map(self) -> Path:
        # Prefer the CSV the downloader copies next to the model; fall back to the model's own.
        bundled = self.model_dir / "yamnet_class_map.csv"
        if bundled.exists():
            return bundled
        return Path(self._model.class_map_path().numpy().decode("utf-8"))

    @property
    def class_names(self) -> list[str]:
        if self._class_names is None:
            raise RuntimeError("YamnetRunner.load() not called")
        return self._class_names

    def classify(self, waveform: np.ndarray) -> np.ndarray:
        """Run YAMNet on a 16 kHz mono float32 waveform; return ``(frames, 521)`` scores."""
        if self._model is None:
            raise RuntimeError("YamnetRunner.load() not called")
        scores, _embeddings, _spectrogram = self._model(waveform)
        return np.asarray(scores)

    def warm_up(self) -> None:
        """Prime the graph with 1 s of silence so the first real clip is not slow."""
        if self._model is None:
            raise RuntimeError("YamnetRunner.load() not called")
        self.classify(np.zeros(16000, dtype=np.float32))
