"""Process-level model cache (C3-04, docs §5).

Holds the loaded YAMNet runner and the current label map. Keyed by ``model_id``:
changing the id triggers a reload of the TF model; the label map can be swapped without a TF
reload (YAMNet weights are the same ``bundled`` SavedModel for every version — only the
label map differs). ``LabelMapper`` is rebuilt from the runner's class names on model load.
"""

from __future__ import annotations

from typing import Any

from app.ml.label_mapper import LabelMapper
from app.ml.yamnet_runner import YamnetRunner


class ModelCache:
    def __init__(self, model_dir: str):
        self._model_dir = model_dir
        self._runner: YamnetRunner | None = None
        self._mapper: LabelMapper | None = None
        self._model_id: str | None = None
        self._label_map: dict[str, Any] | None = None

    @property
    def model_id(self) -> str | None:
        return self._model_id

    @property
    def runner(self) -> YamnetRunner:
        if self._runner is None:
            raise RuntimeError("ModelCache.ensure() not called")
        return self._runner

    @property
    def mapper(self) -> LabelMapper:
        if self._mapper is None:
            raise RuntimeError("ModelCache.ensure() not called")
        return self._mapper

    @property
    def label_map(self) -> dict[str, Any]:
        if self._label_map is None:
            raise RuntimeError("ModelCache.ensure() not called")
        return self._label_map

    def ensure(self, model_id: str, label_map: dict[str, Any], *, warm_up: bool = True) -> bool:
        """Make the cache reflect ``model_id`` + ``label_map``.

        Loads (or reloads) the TF model only when ``model_id`` changes. A label-map-only change
        updates the stored map without touching TensorFlow. Returns True if the TF model was
        (re)loaded, False if only the label map changed or nothing changed.
        """
        reloaded = False
        if self._runner is None or model_id != self._model_id:
            runner = YamnetRunner(self._model_dir)
            runner.load()
            if warm_up:
                runner.warm_up()
            self._runner = runner
            self._mapper = LabelMapper(runner.class_names)
            self._model_id = model_id
            reloaded = True
        self._label_map = label_map
        return reloaded
