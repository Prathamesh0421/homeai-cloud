"""C3-13: dictionary service shaping — Mongo shapes, grouping, CSV (no DB)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services import dictionary_service


def test_mongo_entities_mark_counted_internal():
    entities = {e["name"]: e for e in dictionary_service._mongo_entities()}
    assert "activity_patterns" in entities
    fields = {f["name"]: f for f in entities["activity_patterns"]["fields"]}
    assert fields["counted"]["internal"] is True
    # A public field is not internal.
    assert fields["hours"]["internal"] is False
    # Descriptions are attached from the descriptions module.
    assert "idempotency" in (fields["counted"]["description"] or "").lower()


def test_mongo_entities_cover_all_c3_collections_and_media_events():
    names = {e["name"]: e for e in dictionary_service._mongo_entities()}
    assert {"ai_detections", "activity_patterns", "worker_heartbeats", "media_events"} <= set(names)
    # media_events is C1-owned even though C3 writes processing fields.
    assert names["media_events"]["owner_component"] == "c1"
    assert names["ai_detections"]["owner_component"] == "c3"


def _doc():
    return {
        "version": "1.0.0",
        "generated_at": datetime(2026, 7, 1, tzinfo=UTC),
        "entities": [
            {
                "name": "ml_models",
                "store": "postgres",
                "schema_name": "c3",
                "owner_component": "c3",
                "fields": [
                    {
                        "name": "model_id",
                        "type": "uuid",
                        "nullable": False,
                        "internal": False,
                        "description": "pk",
                    },
                ],
            },
            {
                "name": "activity_patterns",
                "store": "mongo",
                "schema_name": None,
                "owner_component": "c3",
                "fields": [
                    {
                        "name": "counted",
                        "type": "array",
                        "nullable": None,
                        "internal": True,
                        "description": "internal",
                    },
                ],
            },
            {
                "name": "alerts",
                "store": "postgres",
                "schema_name": "c2",
                "owner_component": "c2",
                "fields": [
                    {
                        "name": "alert_id",
                        "type": "uuid",
                        "nullable": False,
                        "internal": False,
                        "description": None,
                    },
                ],
            },
        ],
    }


def test_group_by_component_groups_and_sorts():
    grouped = dictionary_service.group_by_component(_doc())
    comps = [g["component"] for g in grouped["components"]]
    assert comps == ["c2", "c3"]  # sorted
    c3 = next(g for g in grouped["components"] if g["component"] == "c3")
    assert {e["name"] for e in c3["entities"]} == {"ml_models", "activity_patterns"}


def test_to_csv_has_header_and_one_row_per_field():
    csv_text = dictionary_service.to_csv(_doc())
    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    assert lines[0] == "component,store,schema,entity,field,type,nullable,internal,description"
    assert len(lines) == 1 + 3  # header + 3 fields
    # The internal flag is rendered for the counted field.
    counted_row = next(ln for ln in lines if ",counted," in ln)
    assert ",true," in counted_row
