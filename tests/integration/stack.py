"""A small client for the running stack, used by the integration tests (docs/05 §4).

Everything goes through the gateway (``HOMEAI_API_URL``) with real tokens from C4, so the same
tests run against ``make up`` on a laptop or the EC2 host. No direct database access.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import seed_ids

DEMO_CLIPS = ROOT / "demo_clips"
CONTENT_TYPES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".mp4": "video/mp4"}

# Contract 02 §2.3: client id -> (scopes, secret env var, dev default secret).
CLIENTS = {
    "c3-worker": (["alerts:evaluate"], "SERVICE_CLIENT_SECRET_C3", "dev-c3-secret"),
    "device-uploader": (["ingest:write"], "SERVICE_CLIENT_SECRET_DEVICE", "dev-device-secret"),
}


class StackError(AssertionError):
    pass


@dataclass
class Stack:
    base_url: str
    password: str
    timeout: float = 10.0
    _tokens: dict[str, str] = field(default_factory=dict)
    _http: httpx.Client = field(init=False)

    def __post_init__(self) -> None:
        self._http = httpx.Client(base_url=self.base_url.rstrip("/"), timeout=self.timeout)

    @classmethod
    def from_env(cls) -> Stack | None:
        url = os.environ.get("HOMEAI_API_URL")
        if not url:
            return None
        return cls(url, os.environ.get("DEMO_PASSWORD", "Demo!2026"))

    def close(self) -> None:
        self._http.close()

    # --- tokens -------------------------------------------------------------------------

    def user_token(self, email: str) -> str:
        if email not in self._tokens:
            body = self._ok(
                self._http.post(
                    "/api/v1/auth/login", json={"email": email, "password": self.password}
                )
            )
            self._tokens[email] = body["data"]["token"]
        return self._tokens[email]

    def service_token(self, client_id: str) -> str:
        if client_id not in self._tokens:
            scopes, env_var, default = CLIENTS[client_id]
            body = self._ok(
                self._http.post(
                    "/api/v1/auth/service-token",
                    json={
                        "client_id": client_id,
                        "client_secret": os.environ.get(env_var, default),
                        "scope": scopes,
                    },
                )
            )
            self._tokens[client_id] = body["data"]["token"]
        return self._tokens[client_id]

    # --- HTTP ---------------------------------------------------------------------------

    def request(self, method: str, path: str, token: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
        return self._http.request(method, path, headers=headers, **kwargs)

    def call(self, method: str, path: str, token: str, **kwargs: Any) -> Any:
        r = self.request(method, path, token, **kwargs)
        if r.status_code == 204:
            return None
        return self._ok(r)

    @staticmethod
    def _ok(r: httpx.Response) -> Any:
        if r.status_code >= 400:
            raise StackError(
                f"{r.request.method} {r.request.url.path} -> {r.status_code}: {r.text[:400]}"
            )
        return r.json()

    # --- the pipeline -------------------------------------------------------------------

    def upload_clip(self, feed: str, clip: str) -> str:
        """C1 ingest as the device uploader; returns the new ``media_id``."""
        feed_id, *_, media_kind, _enabled = seed_ids.FEEDS[feed]
        path = DEMO_CLIPS / clip
        if not path.exists():
            raise StackError(f"{path} missing: run scripts/fetch_demo_clips.sh")
        with path.open("rb") as fh:
            body = self.call(
                "POST",
                "/api/v1/ingest/clip",
                self.service_token("device-uploader"),
                data={
                    "feed_id": feed_id,
                    "media_kind": media_kind,
                    "captured_at": datetime.now(UTC).isoformat(),
                },
                files={"file": (path.name, fh, CONTENT_TYPES[path.suffix])},
            )
        return body["data"]["media_id"]

    def wait_for_detection(self, media_id: str, token: str, within: float = 60.0) -> dict:
        """Polls C3's records until the clip is analyzed and handed off; returns the detection
        (``id`` is the detection id: the records API renames Mongo's ``_id``)."""
        deadline = time.monotonic() + within
        event: dict = {}
        while time.monotonic() < deadline:
            r = self.request("GET", f"/api/v1/records/clips/{media_id}", token)
            if r.status_code == 200:
                event = r.json()["data"]
                if event.get("status") == "failed":
                    raise StackError(f"C3 failed clip {media_id}: {event.get('error')}")
                if event.get("status") == "analyzed":
                    break
            time.sleep(1)
        else:
            raise StackError(f"clip {media_id} not analyzed within {within:.0f} s: {event}")
        if event.get("handoff_status") != "done":
            raise StackError(
                f"C3 could not hand clip {media_id} to C2 (handoff_status="
                f"{event.get('handoff_status')}); is HANDOFF_MODE=call set on c3-worker?"
            )
        return self.call("GET", f"/api/v1/records/detections/{event['detection_id']}", token)[
            "data"
        ]

    def evaluate(self, detection: dict) -> httpx.Response:
        """``POST /alerts/evaluate`` as C3 sends it (contract 02 §4.3), from the stored doc."""
        body = {
            "detection_id": detection["id"],
            "media_id": detection["media_id"],
            "house_id": detection["house_id"],
            "room_id": detection.get("room_id"),
            "top_label": detection["top_label"],
            "top_confidence": detection["top_confidence"],
            "labels": detection.get("labels", []),
            "detected_at": detection["detected_at"],
        }
        return self.request(
            "POST", "/api/v1/alerts/evaluate", self.service_token("c3-worker"), json=body
        )
