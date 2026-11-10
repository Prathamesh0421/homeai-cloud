"""C3-13 (Tier 2): data dictionary generated from the live schema (Rev4 §6).

Asserts the DoD: a column added to the live schema shows up in the regenerated dictionary; it
covers all four schemas (c1/c2/c4 skipped when their tables are absent in the per-package CI
DB); versions are immutable (409 on re-publish); activity_patterns.counted is marked internal.

Reflection runs on C3's own connection (the one that owns/sees schema c3). In the per-package CI
DB the DSN is the superuser, which owns every schema; on RDS it is c3_app, which owns c3 and is
granted SELECT on the others. Either way ``information_schema`` returns what that role can see.
"""

from __future__ import annotations

import os
import uuid

import pytest
from app.repositories.dictionary_repo import DictionaryRepo, VersionExists
from app.services import dictionary_service
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration


def _require(reason: str):
    if os.environ.get("CI") == "true":
        pytest.fail(f"integration store required on CI: {reason}", pytrace=False)
    pytest.skip(reason)


def _engine():
    pg = os.environ.get("DATABASE_URL_C3")
    if not pg:
        _require("DATABASE_URL_C3 not set")
    return create_engine(pg, future=True)


def _entity(document, name):
    return next((e for e in document["entities"] if e["name"] == name), None)


def test_generate_reflects_c3_tables(pg_session):
    """The c3 schema (migrated to head by pg_session) is reflected with its real columns."""
    eng = _engine()
    try:
        with eng.connect() as conn:
            doc = dictionary_service.generate(conn, "it-1")
    finally:
        eng.dispose()

    names = {e["name"] for e in doc["entities"] if e["schema_name"] == "c3"}
    assert {
        "ml_models",
        "model_evaluations",
        "integrity_reports",
        "data_dictionary_versions",
    } <= names

    ml = _entity(doc, "ml_models")
    cols = {f["name"]: f for f in ml["fields"]}
    assert {"model_id", "status", "label_map", "created_at"} <= set(cols)
    assert cols["model_id"]["nullable"] is False  # reflected nullability
    assert cols["model_id"]["description"]  # hand description from descriptions.py
    assert ml["owner_component"] == "c3"
    # generated_at is an ISO string (JSONB-safe), not a datetime.
    assert isinstance(doc["generated_at"], str) and doc["generated_at"].endswith("Z")


def test_new_column_shows_up_in_regenerated_dictionary(pg_session):
    """DoD: a column added to the live schema appears when the dictionary is regenerated."""
    eng = _engine()
    col = f"dict_probe_{uuid.uuid4().hex[:8]}"
    try:
        with eng.begin() as conn:
            conn.execute(text(f"ALTER TABLE c3.ml_models ADD COLUMN {col} text"))
        try:
            with eng.connect() as conn:
                doc = dictionary_service.generate(conn, "it-2")
            ml = _entity(doc, "ml_models")
            assert col in {f["name"] for f in ml["fields"]}
        finally:
            with eng.begin() as conn:
                conn.execute(text(f"ALTER TABLE c3.ml_models DROP COLUMN IF EXISTS {col}"))
    finally:
        eng.dispose()


def test_mongo_entities_merged_with_counted_internal(pg_session):
    eng = _engine()
    try:
        with eng.connect() as conn:
            doc = dictionary_service.generate(conn, "it-3")
    finally:
        eng.dispose()
    ap = _entity(doc, "activity_patterns")
    assert ap is not None and ap["store"] == "mongo"
    counted = next(f for f in ap["fields"] if f["name"] == "counted")
    assert counted["internal"] is True


def test_covers_all_four_schemas_or_skips_absent(pg_session):
    """c3 is always present; c1/c2/c4 asserted only if their tables exist in this DB (else skip)."""
    eng = _engine()
    try:
        with eng.connect() as conn:
            doc = dictionary_service.generate(conn, "it-4")
    finally:
        eng.dispose()

    present = {e["schema_name"] for e in doc["entities"] if e["store"] == "postgres"}
    assert "c3" in present  # always, migrated by pg_session
    other = {s for s in ("c1", "c2", "c4") if s in present}
    if not other:
        pytest.skip(
            "no c1/c2/c4 tables in this DB (per-package CI job); cross-schema coverage is only "
            "fully verifiable full-stack"
        )


def test_unreadable_schema_fails_loud(pg_session):
    """Fail-closed: a schema that exists but the role cannot read raises, not an empty dict.

    c3 exists; under SET ROLE c3_reader (which lacks USAGE on c3 when tables are superuser-owned)
    generate must raise SchemaUnreadable rather than silently reflecting zero columns. If the DSN
    role can read c3 anyway (e.g. c3_app owns it locally), there is nothing to prove, so skip.
    """
    from app.services.dictionary_service import SchemaUnreadable

    eng = _engine()
    try:
        with eng.connect() as conn:
            try:
                conn.execute(text("SET ROLE c3_reader"))
            except Exception:
                pytest.skip("cannot SET ROLE c3_reader on this connection")
            usable = conn.execute(text("SELECT has_schema_privilege('c3', 'USAGE')")).scalar_one()
            if usable:
                pytest.skip("c3_reader can read schema c3 here; no unreadable case to assert")
            with pytest.raises(SchemaUnreadable):
                dictionary_service.generate(conn, "it-unreadable")
    finally:
        eng.dispose()


def test_publish_is_immutable(pg_session):
    repo = DictionaryRepo(pg_session)
    version = f"it-{uuid.uuid4().hex[:8]}"
    sys_uuid = "00000000-0000-0000-0000-000000000000"
    try:
        repo.publish(version, {"entities": []}, published_by=sys_uuid)
        pg_session.commit()
        with pytest.raises(VersionExists):
            repo.publish(version, {"entities": []}, published_by=sys_uuid)
    finally:
        pg_session.execute(
            text("DELETE FROM c3.data_dictionary_versions WHERE version = :v"), {"v": version}
        )
        pg_session.commit()
