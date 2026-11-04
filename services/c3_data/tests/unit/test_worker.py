"""C3-06: worker helpers and the claim/retry flow with fake repos (no TF/Mongo/S3)."""

from __future__ import annotations

from app import worker as worker_mod


def test_worker_id_is_hostname_pid():
    wid = worker_mod.worker_id()
    host, _, pid = wid.rpartition("-")
    assert host
    assert pid.isdigit()


class _Events:
    def __init__(self, ev):
        self._ev = ev
        self.failures: list[tuple] = []

    def claim_next(self, worker_id):
        ev, self._ev = self._ev, None
        return ev

    def mark_failure(self, media_id, attempts, error):
        self.failures.append((media_id, attempts))
        return "queued" if attempts < 3 else "failed"


class _Pipeline:
    def __init__(self, classify=None, finish=None):
        self._classify, self._finish = classify, finish
        self.finished: list[str] = []

    def classify(self, ev, *args, **kwargs):
        return self._classify(ev)

    def finish_existing(self, ev):
        self.finished.append(ev["_id"])
        return self._finish(ev)


def _worker(events, pipeline):
    w = worker_mod.Worker.__new__(worker_mod.Worker)  # no TF / Mongo / S3
    w.id, w.events, w.pipeline = "test-worker", events, pipeline
    w._model = {"model_id": "m1", "version": "1.0.0", "label_map": {}}
    w.cache = type("Cache", (), {"runner": None, "mapper": None})()
    w.processed = w.failed = w._latency_total = 0
    return w


def _exists(ev):
    raise worker_mod.DetectionExistsError(ev["_id"])


def test_clip_with_a_stored_detection_is_finished_not_left_processing():
    # Attempt 1 stored the detection, then failed; attempt 2 must finish the clip.
    events = _Events({"_id": "media-1", "attempts": 2})
    pipeline = _Pipeline(classify=_exists, finish=lambda ev: {"_id": "det-1"})
    w = _worker(events, pipeline)
    assert w.process_one() is True
    assert pipeline.finished == ["media-1"]
    assert events.failures == []
    assert (w.processed, w.failed) == (0, 0)


def test_finishing_failure_counts_as_an_attempt():
    def handoff_down(ev):
        raise RuntimeError("mongo blip")

    events = _Events({"_id": "media-1", "attempts": 3})
    w = _worker(events, _Pipeline(classify=_exists, finish=handoff_down))
    w.process_one()
    assert events.failures == [("media-1", 3)]  # -> failed, not reclaimed forever
    assert w.failed == 1


def test_missing_detection_after_dedupe_is_retried():
    events = _Events({"_id": "media-1", "attempts": 1})
    w = _worker(events, _Pipeline(classify=_exists, finish=lambda ev: None))
    w.process_one()
    assert events.failures == [("media-1", 1)]


def test_classified_clip_is_counted():
    events = _Events({"_id": "media-1", "attempts": 1})
    detection = {"_id": "det-1", "top_label": "speech", "_latency_ms": 40}
    w = _worker(events, _Pipeline(classify=lambda ev: detection))
    w.process_one()
    assert (w.processed, w._latency_total, events.failures) == (1, 40, [])


def test_empty_queue():
    assert _worker(_Events(None), _Pipeline()).process_one() is False
