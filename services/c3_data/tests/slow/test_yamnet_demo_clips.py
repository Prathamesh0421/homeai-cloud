"""C3-05 (slow): real YAMNet on demo clips (docs §7).

Marked ``slow``: needs TensorFlow, the bundled YAMNet model, ffmpeg, and demo_clips/. Run before
demos with ``pytest -m slow``; skipped automatically when any prerequisite is missing.

    pytest services/c3_data -m slow
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
CLIPS = REPO_ROOT / "demo_clips"
MODEL_DIR = Path("/models")

pytestmark = pytest.mark.slow

_missing = (
    shutil.which("ffmpeg") is None
    or not CLIPS.exists()
    or not (MODEL_DIR / "yamnet" / "1" / "saved_model.pb").exists()
)
pytest_skip = pytest.mark.skipif(
    _missing, reason="needs ffmpeg + demo_clips/ + bundled /models/yamnet/1"
)


def _load_seed_label_map():
    path = REPO_ROOT / "services" / "c3_data" / "alembic" / "versions" / "0002_seed_yamnet.py"
    spec = importlib.util.spec_from_file_location("seed_0002", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LABEL_MAP


@pytest_skip
@pytest.mark.parametrize(
    ("clip", "expected"),
    [
        ("glass_break.wav", "glass_break"),
        ("dog.wav", "dog"),
        ("silence.wav", "none"),
    ],
)
def test_real_yamnet_on_demo_clip(clip, expected):
    from app.ml.model_cache import ModelCache
    from app.services.classification_pipeline import classify_bytes

    label_map = _load_seed_label_map()
    cache = ModelCache(str(MODEL_DIR))
    cache.ensure("yamnet-1.0.0", label_map, warm_up=False)

    raw = (CLIPS / clip).read_bytes()
    result = classify_bytes(raw, cache.runner, cache.mapper, label_map)
    assert result.top_label == expected
