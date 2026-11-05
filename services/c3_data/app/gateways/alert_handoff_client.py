"""Hand a detection off to C2's alert evaluator (C3-09, docs §4.3, contract §4.3).

Two modes (``HANDOFF_MODE``):
  log  -> log the payload and report success ("done"); for independent development without C2.
  call -> POST the payload to C2 ``/api/v1/alerts/evaluate`` with a service token.

The client is used as the pipeline's ``on_detection`` hook: it takes a stored ``ai_detections``
document and returns the resulting ``handoff_status`` ("done" or "pending"). C2 is idempotent on
``detection_id`` (a re-classify keeps the same id), so re-sending is safe and never raises a
second alert. ``ServiceHttpClient`` already retries 502/503/504 with 2/4/8 s backoff; if it still
fails the status is "pending" and the integrity job re-sends it later.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from homeai_common.service_client import ServiceHttpClient, ServiceTokenProvider

logger = logging.getLogger("c3.handoff")

EVALUATE_PATH = "/api/v1/alerts/evaluate"


def _payload(detection: dict[str, Any]) -> dict[str, Any]:
    """Build the C2 evaluate request body (contract §4.3) from a detection document."""
    detected_at = detection.get("detected_at")
    if hasattr(detected_at, "isoformat"):
        detected_at = detected_at.isoformat().replace("+00:00", "Z")
    return {
        "detection_id": detection["_id"],
        "media_id": detection["media_id"],
        "house_id": detection["house_id"],
        "room_id": detection.get("room_id"),
        "top_label": detection["top_label"],
        "top_confidence": detection["top_confidence"],
        "labels": [
            {"label": label["label"], "confidence": label["confidence"]}
            for label in detection.get("labels", [])
        ],
        "detected_at": detected_at,
    }


class LogHandoff:
    """HANDOFF_MODE=log: record the payload and report success."""

    def __call__(self, detection: dict[str, Any]) -> str:
        logger.info(
            "handoff (log mode)",
            extra={"detection_id": detection["_id"], "top_label": detection["top_label"]},
        )
        return "done"


class AlertHandoffClient:
    """HANDOFF_MODE=call: POST the detection to C2's evaluate endpoint with a service token."""

    def __init__(self, client: ServiceHttpClient):
        self.client = client

    @classmethod
    def from_settings(cls, settings) -> AlertHandoffClient:
        provider = ServiceTokenProvider(
            c4_base_url=settings.c4_base_url,
            client_id="c3-worker",
            client_secret=settings.service_client_secret or "",
            scopes=["alerts:evaluate"],
        )
        http = ServiceHttpClient(base_url=settings.c2_base_url, token_provider=provider)
        return cls(http)

    def __call__(self, detection: dict[str, Any]) -> str:
        """Return ``done`` on a 2xx decision, ``pending`` on failure (retries exhausted)."""
        try:
            resp = self.client.post(EVALUATE_PATH, json=_payload(detection))
        except Exception as exc:
            logger.warning(
                "handoff failed; marking pending",
                extra={"detection_id": detection["_id"], "error": str(exc)[:200]},
            )
            return "pending"
        if resp.status_code in (200, 201):
            decision = None
            with contextlib.suppress(Exception):
                decision = resp.json().get("data", {}).get("decision")
            logger.info(
                "handoff ok",
                extra={"detection_id": detection["_id"], "decision": decision},
            )
            return "done"
        logger.warning(
            "handoff non-2xx; marking pending",
            extra={"detection_id": detection["_id"], "status": resp.status_code},
        )
        return "pending"


def build_handoff(settings):
    """Pick the handoff hook based on HANDOFF_MODE."""
    if settings.handoff_mode == "call":
        return AlertHandoffClient.from_settings(settings)
    return LogHandoff()
