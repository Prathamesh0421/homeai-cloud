"""Tier 3 contract: FakeDetectionRepo must behave like the real DetectionRepo.

The same assertion body runs against both adapters. If the fake drifts from real Mongo on the
points the unit tests rely on (notably ``_id`` immutability on replace), this fails — which is
exactly the signal that was missing when the Phase 5 fake hid the ``_id`` bug.

The real-adapter case uses Mongo (skips locally, fails on CI if missing); the fake case always
runs. Both share ``_assert_contract``.
"""

from __future__ import annotations

import os
import uuid

import pytest
from app.repositories.detection_repo import DetectionRepo

from tests.fakes import FakeDetectionRepo


def _detection(media_id: str, label: str) -> dict:
    return {"_id": str(uuid.uuid4()), "media_id": media_id, "top_label": label}


def _assert_contract(repo) -> None:
    mid = "media-contract-1"
    assert repo.exists_for_media(mid) is False
    assert repo.get_by_media(mid) is None

    first = _detection(mid, "speech")
    repo.upsert_by_media(first)
    assert repo.exists_for_media(mid) is True
    assert repo.get_by_media(mid)["_id"] == first["_id"]
    assert repo.get_by_media(mid)["top_label"] == "speech"

    # Replace with a fresh _id: the stored id must NOT change, and it is written back.
    again = _detection(mid, "glass_break")
    repo.upsert_by_media(again)
    stored = repo.get_by_media(mid)
    assert stored["_id"] == first["_id"]
    assert stored["top_label"] == "glass_break"
    assert again["_id"] == first["_id"]


def test_fake_detection_repo_matches_contract():
    _assert_contract(FakeDetectionRepo())


@pytest.mark.integration
def test_real_detection_repo_matches_contract():
    url = os.environ.get("MONGO_URL_C3")
    if not url:
        if os.environ.get("CI") == "true":
            pytest.fail("MONGO_URL_C3 required on CI", pytrace=False)
        pytest.skip("MONGO_URL_C3 not set")
    from pymongo import MongoClient

    client = MongoClient(url, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
    except Exception as exc:
        pytest.skip(f"Mongo unreachable: {type(exc).__name__}")
    col = client.get_default_database()[f"ai_detections_contract_{uuid.uuid4().hex[:8]}"]
    try:
        _assert_contract(DetectionRepo(col))
    finally:
        col.drop()
        client.close()
