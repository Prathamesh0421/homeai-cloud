"""C3-07: model lifecycle rules (create/clone/validate, label-map edit, activate, retire)."""

from __future__ import annotations

import pytest
from app.services.model_registry import ModelRegistry
from homeai_common.errors import ApiError

CLASSES = ["Glass", "Shatter", "Dog", "Bark", "Speech"]


class _Model:
    def __init__(self, model_id, name, version, status, label_map):
        self.model_id = model_id
        self.name = name
        self.version = version
        self.status = status
        self.label_map = label_map
        self.activated_by = None
        self.activated_at = None


class _FakeRepo:
    def __init__(self, models=None):
        self.models = {m.model_id: m for m in (models or [])}
        self._seq = 0

    def get(self, model_id):
        return self.models.get(model_id)

    def get_active(self):
        return next((m for m in self.models.values() if m.status == "active"), None)

    def get_by_name_version(self, name, version):
        return next(
            (m for m in self.models.values() if m.name == name and m.version == version), None
        )

    def create(self, *, name, version, label_map, created_by, source="bundled", notes=None):
        self._seq += 1
        m = _Model(f"m{self._seq}", name, version, "registered", label_map)
        self.models[m.model_id] = m
        return m

    def update_label_map(self, model, label_map):
        model.label_map = label_map
        model.status = "registered"
        return model

    def activate(self, model, *, activated_by):
        cur = self.get_active()
        if cur and cur.model_id != model.model_id:
            cur.status = "retired"
        model.status = "active"
        model.activated_by = activated_by

    def retire(self, model):
        model.status = "retired"


def _entry(label="glass_break", classes=("Glass",), rule="max"):
    return {
        "home_label": label,
        "source_classes": list(classes),
        "min_confidence": 0.5,
        "rule": rule,
    }


def _lm(*entries):
    return {"version": "x", "entries": list(entries) or [_entry()]}


def _reg(models=None):
    return ModelRegistry(_FakeRepo(models), CLASSES)


def test_create_clones_label_map_from_active_when_omitted():
    active = _Model("m0", "yamnet", "1.0.0", "active", _lm(_entry()))
    reg = _reg([active])
    m = reg.create_version(name="yamnet", version="1.1.0", created_by="u1")
    assert m.status == "registered"
    assert m.label_map == active.label_map


def test_create_duplicate_version_409():
    existing = _Model("m0", "yamnet", "1.0.0", "active", _lm())
    reg = _reg([existing])
    with pytest.raises(ApiError) as e:
        reg.create_version(name="yamnet", version="1.0.0", created_by="u1")
    assert e.value.status_code == 409


def test_create_invalid_label_map_422():
    active = _Model("m0", "yamnet", "1.0.0", "active", _lm())
    reg = _reg([active])
    bad = _lm(_entry(classes=("Nonexistent",)))
    with pytest.raises(ApiError) as e:
        reg.create_version(name="yamnet", version="2.0.0", created_by="u1", label_map=bad)
    assert e.value.status_code == 422


def test_update_label_map_on_active_is_409_model_active():
    active = _Model("m0", "yamnet", "1.0.0", "active", _lm())
    reg = _reg([active])
    with pytest.raises(ApiError) as e:
        reg.update_label_map("m0", _lm(_entry(classes=("Dog",), label="dog")))
    assert e.value.status_code == 409
    assert e.value.code == "model_active"


def test_update_label_map_resets_to_registered():
    m = _Model("m0", "yamnet", "1.1.0", "evaluated", _lm())
    reg = _reg([m])
    out = reg.update_label_map("m0", _lm(_entry(classes=("Dog",), label="dog")))
    assert out.status == "registered"


def test_activate_requires_evaluated_or_retired():
    m = _Model("m0", "yamnet", "1.1.0", "registered", _lm())
    reg = _reg([m])
    with pytest.raises(ApiError) as e:
        reg.activate("m0", activated_by="u1")
    assert e.value.status_code == 422


def test_activate_swaps_previous_active_to_retired():
    active = _Model("m0", "yamnet", "1.0.0", "active", _lm())
    candidate = _Model("m1", "yamnet", "1.1.0", "evaluated", _lm())
    reg = _reg([active, candidate])
    reg.activate("m1", activated_by="u1")
    assert candidate.status == "active"
    assert active.status == "retired"


def test_retire_active_is_409():
    active = _Model("m0", "yamnet", "1.0.0", "active", _lm())
    reg = _reg([active])
    with pytest.raises(ApiError) as e:
        reg.retire("m0")
    assert e.value.status_code == 409
