"""C3-04: model cache reloads TF only on model_id change, not on label-map change."""

from __future__ import annotations

import app.ml.model_cache as mc


class _FakeRunner:
    loads = 0

    def __init__(self, model_dir):
        self.model_dir = model_dir
        self.class_names = ["Glass", "Dog"]

    def load(self):
        _FakeRunner.loads += 1

    def warm_up(self):
        pass


def _patch(monkeypatch):
    _FakeRunner.loads = 0
    monkeypatch.setattr(mc, "YamnetRunner", _FakeRunner)
    # LabelMapper just needs class_names; the real one is cheap/pure, keep it.


def test_first_ensure_loads_model(monkeypatch):
    _patch(monkeypatch)
    cache = mc.ModelCache("/models")
    reloaded = cache.ensure("m1", {"entries": []}, warm_up=False)
    assert reloaded is True
    assert _FakeRunner.loads == 1
    assert cache.model_id == "m1"


def test_label_map_only_change_does_not_reload_tf(monkeypatch):
    _patch(monkeypatch)
    cache = mc.ModelCache("/models")
    cache.ensure("m1", {"entries": []}, warm_up=False)
    reloaded = cache.ensure("m1", {"entries": [{"home_label": "x"}]}, warm_up=False)
    assert reloaded is False
    assert _FakeRunner.loads == 1  # no extra load
    assert cache.label_map["entries"] == [{"home_label": "x"}]


def test_model_id_change_reloads_tf(monkeypatch):
    _patch(monkeypatch)
    cache = mc.ModelCache("/models")
    cache.ensure("m1", {"entries": []}, warm_up=False)
    reloaded = cache.ensure("m2", {"entries": []}, warm_up=False)
    assert reloaded is True
    assert _FakeRunner.loads == 2
    assert cache.model_id == "m2"
