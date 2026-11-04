"""C3 inference worker (``python -m app.worker``, C3-06, docs §4.1).

Loop: load the active model, then repeatedly claim the oldest queued (or visibility-timed-out)
clip atomically, classify it through the pipeline, and record the result. On error a clip goes
back to ``queued`` until it has had 3 attempts, then ``failed``. A background thread writes a
heartbeat every 10 s and re-checks whether the active model changed (hot reload).

Concurrency is safe for ``--scale c3-worker=N``: the claim is a single atomic
``find_one_and_update`` so no two workers take the same clip.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import socket
import threading
from datetime import UTC, datetime
from types import FrameType

from homeai_common import db, mongo
from homeai_common.logging import configure_logging

from app.gateways.s3_gateway import S3ClipGateway
from app.ml.model_cache import ModelCache
from app.repositories.detection_repo import COLLECTION as DET_COLLECTION
from app.repositories.detection_repo import DetectionRepo
from app.repositories.heartbeat_repo import COLLECTION as HB_COLLECTION
from app.repositories.heartbeat_repo import HeartbeatRepo
from app.repositories.media_event_repo import COLLECTION as EV_COLLECTION
from app.repositories.media_event_repo import MediaEventRepo
from app.repositories.ml_model_repo import MlModelRepo
from app.services.classification_pipeline import ClassificationPipeline, DetectionExistsError
from app.settings import SERVICE_NAME, Settings, get_settings

logger = logging.getLogger("c3.worker")


def worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _active_model_dict(settings: Settings) -> dict | None:
    """Fetch the active model as a plain dict (id/name/version/label_map), or None."""
    with db.session_scope() as session:  # type: Session
        model = MlModelRepo(session).get_active()
        if model is None:
            return None
        return {
            "model_id": model.model_id,
            "name": model.name,
            "version": model.version,
            "label_map": model.label_map,
        }


class Worker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.id = worker_id()
        self.hostname = socket.gethostname()
        self.started_at = datetime.now(UTC)
        self.cache = ModelCache(settings.model_dir)
        self._model: dict | None = None

        mdb = mongo.get_mongo_db(settings.mongo_url)
        self.detections = DetectionRepo(mdb[DET_COLLECTION])
        self.events = MediaEventRepo(mdb[EV_COLLECTION])
        self.heartbeats = HeartbeatRepo(mdb[HB_COLLECTION])
        s3 = S3ClipGateway(settings.s3_bucket, settings.aws_region, settings.aws_endpoint)
        self.pipeline = ClassificationPipeline(
            s3_get=s3.get_bytes,
            detection_repo=self.detections,
            media_event_repo=self.events,
            # Phase 7 replaces this with the real C2 handoff; log mode for now.
        )

        self.processed = 0
        self.failed = 0
        self._latency_total = 0
        self._stop = threading.Event()

    # -- model management ---------------------------------------------------
    def reload_model_if_changed(self) -> None:
        """Load the active model into the cache if its id changed (hot reload)."""
        model = _active_model_dict(self.settings)
        if model is None:
            return
        if self._model is None or model["model_id"] != self._model["model_id"]:
            self.cache.ensure(model["model_id"], model["label_map"], warm_up=True)
            self._model = model
            logger.info(
                "active model loaded",
                extra={"model_id": model["model_id"], "version": model["version"]},
            )
        else:
            # Same model id: refresh the label map in the cache without a TF reload.
            self.cache.ensure(model["model_id"], model["label_map"], warm_up=False)
            self._model = model

    # -- heartbeat ----------------------------------------------------------
    def write_heartbeat(self) -> None:
        avg = (self._latency_total / self.processed) if self.processed else 0.0
        with contextlib.suppress(Exception):
            self.heartbeats.beat(
                worker_id=self.id,
                hostname=self.hostname,
                model_id=self._model["model_id"] if self._model else None,
                model_version=self._model["version"] if self._model else None,
                started_at=self.started_at,
                processed=self.processed,
                failed=self.failed,
                avg_latency_ms=avg,
            )

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            with contextlib.suppress(Exception):
                self.reload_model_if_changed()
            self.write_heartbeat()
            self._stop.wait(self.settings.worker_heartbeat_interval)

    # -- processing ---------------------------------------------------------
    def process_one(self) -> bool:
        """Claim and process one clip. Returns True if a clip was handled, False if queue empty."""
        ev = self.events.claim_next(self.id)
        if ev is None:
            return False

        media_id = ev["_id"]
        try:
            try:
                detection = self.pipeline.classify(
                    ev,
                    self._model,
                    self.cache.runner,
                    self.cache.mapper,
                    self._model["label_map"],
                )
            except DetectionExistsError:
                # Stored by an earlier attempt that failed (or crashed) before the clip was
                # marked analyzed. Finish that run: otherwise the clip stays "processing" and
                # is reclaimed forever, and C2 may never get the detection.
                detection = self.pipeline.finish_existing(ev)
                if detection is None:  # removed in between: retry like any other failure
                    raise
                logger.info(
                    "detection already stored; finished the clip", extra={"media_id": media_id}
                )
            else:
                self.processed += 1
                self._latency_total += int(detection.get("_latency_ms", 0))
                logger.info(
                    "classified",
                    extra={"media_id": media_id, "top_label": detection["top_label"]},
                )
        except Exception as exc:  # pipeline/S3/decode/handoff failures -> retry or fail
            self.failed += 1
            new_status = self.events.mark_failure(media_id, int(ev.get("attempts", 1)), str(exc))
            logger.warning(
                "classify failed",
                extra={"media_id": media_id, "status": new_status, "error": str(exc)[:200]},
            )
        return True

    def run(self) -> None:
        self.reload_model_if_changed()
        if self._model is None:
            logger.error("no active model; worker idling")
        hb = threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True)
        hb.start()
        logger.info("C3 worker started", extra={"worker_id": self.id})

        while not self._stop.is_set():
            handled = False
            if self._model is not None:
                with contextlib.suppress(Exception):
                    handled = self.process_one()
            if not handled:
                self._stop.wait(self.settings.worker_sleep)

    def stop(self) -> None:
        self._stop.set()


def main() -> None:
    settings = get_settings()
    configure_logging(f"{SERVICE_NAME}-worker", settings.log_level)
    if settings.database_url:
        db.configure_db(settings.database_url, reader_url=settings.database_reader_url)

    worker = Worker(settings)

    def _handle_stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("C3 worker stopping", extra={"signal": signum})
        worker.stop()

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    try:
        worker.run()
    finally:
        db.dispose_db()
        mongo.close_mongo()


if __name__ == "__main__":
    main()
