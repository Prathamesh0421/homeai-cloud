"""C3-02: ORM classes import and the seeded label map is well-formed."""

from __future__ import annotations

import importlib.util
from pathlib import Path

EXPECTED_LABELS = {
    "smoke_alarm",
    "distress_sound",
    "glass_break",
    "fall_indicator",
    "cough",
    "speech",
    "dog",
}
VALID_RULES = {"max", "mean", "consec2"}


def test_orm_classes_import():
    from app.models.orm import (
        DataDictionaryVersion,
        IntegrityReport,
        MlModel,
        ModelEvaluation,
    )

    # Tables registered on the c3 schema.
    for cls in (MlModel, ModelEvaluation, IntegrityReport, DataDictionaryVersion):
        assert cls.__table__.schema == "c3"


def _load_seed_module():
    # Module filename starts with a digit, so load it by path.
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0002_seed_yamnet.py"
    spec = importlib.util.spec_from_file_location("seed_0002", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_label_map_has_seven_valid_entries():
    seed = _load_seed_module()
    entries = seed.LABEL_MAP["entries"]
    assert len(entries) == 7
    assert {e["home_label"] for e in entries} == EXPECTED_LABELS
    for e in entries:
        assert e["rule"] in VALID_RULES
        assert 0.0 <= e["min_confidence"] <= 1.0
        assert len(e["source_classes"]) >= 1
    assert seed.LABEL_MAP["version"] == "1.0.0"
