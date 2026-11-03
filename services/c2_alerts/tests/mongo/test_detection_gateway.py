"""MongoDetectionGateway against MongoDB, and the fake against the same expectations."""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
from app.gateways.detection_gateway import MongoDetectionGateway
from app.gateways.types import (
    DependencyUnavailableError,
    Detection,
    InvalidDetectionError,
)
from pymongo import MongoClient

from tests.factories import HOUSE_A1, ROOM_A1_KITCHEN, TENANT_A, uid
from tests.fakes import FakeDetectionReader

DETECTED_AT = datetime(2026, 10, 24, 18, 40, 50, tzinfo=UTC)


def contract_doc(**overrides) -> dict:
    """The ai_detections document from contracts §4.2 (plus an unknown field C3 might add)."""
    doc = {
        "_id": uid(),
        "media_id": uid(),
        "tenant_id": TENANT_A,
        "house_id": HOUSE_A1,
        "room_id": ROOM_A1_KITCHEN,
        "model": {"model_id": uid(), "name": "yamnet", "version": "1.0.0"},
        "labels": [
            {
                "label": "glass_break",
                "confidence": 0.78,
                "source_class": "Glass",
                "start_s": 2.9,
                "end_s": 4.8,
            }
        ],
        "top_label": "glass_break",
        "top_confidence": 0.78,
        "detected_at": DETECTED_AT,
        "pipeline_ms": 412,
    }
    doc.update(overrides)
    return doc


@pytest.fixture(params=["mongo", "fake"])
def store(request):
    """(insert(doc), reader) for the real gateway or the fake."""
    if request.param == "mongo":
        coll = request.getfixturevalue("collection")
        return lambda doc: coll.insert_one(copy.deepcopy(doc)), MongoDetectionGateway(coll)
    fake = FakeDetectionReader()
    return lambda doc: fake.add(Detection.model_validate(doc)), fake


def test_reads_contract_document(store):
    insert, reader = store
    doc = contract_doc()
    insert(doc)
    d = reader.get(doc["_id"])
    assert d.detection_id == doc["_id"]
    assert (d.house_id, d.room_id, d.tenant_id) == (HOUSE_A1, ROOM_A1_KITCHEN, TENANT_A)
    assert (d.top_label, d.top_confidence) == ("glass_break", 0.78)
    assert d.labels[0].source_class == "Glass"
    assert d.model.version == "1.0.0"
    assert d.detected_at == DETECTED_AT
    assert d.detected_at.tzinfo is not None


def test_no_match_document(store):
    insert, reader = store
    doc = contract_doc(labels=[], top_label="none", top_confidence=0.0, room_id=None)
    insert(doc)
    d = reader.get(doc["_id"])
    assert (d.labels, d.top_label, d.top_confidence, d.room_id) == ([], "none", 0.0, None)


def test_unknown_detection_is_none(store):
    _, reader = store
    assert reader.get(uid()) is None


def test_malformed_document_is_invalid(collection):
    doc = contract_doc()
    del doc["top_label"]
    collection.insert_one(doc)
    with pytest.raises(InvalidDetectionError, match="top_label"):
        MongoDetectionGateway(collection).get(doc["_id"])


def test_mongo_down_is_dependency_unavailable():
    client = MongoClient("mongodb://127.0.0.1:1", serverSelectionTimeoutMS=200)
    gateway = MongoDetectionGateway(client["homeai"]["ai_detections"])
    with pytest.raises(DependencyUnavailableError) as exc:
        gateway.get(uid())
    assert exc.value.source == "c3"
    client.close()


def test_fake_can_simulate_outage():
    fake = FakeDetectionReader()
    fake.down = True
    with pytest.raises(DependencyUnavailableError):
        fake.get(uid())
