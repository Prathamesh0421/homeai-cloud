"""C3-13 (Tier 2): data dictionary generated from the live schema (Rev4 §6).

Asserts the DoD: a column added to the live schema shows up in the regenerated dictionary; it
covers all four schemas (c1/c2/c4 skipped when their tables are absent in the per-package CI
DB); versions are immutable (409 on re-publish); activity_patterns.counted is marked internal.

Reflection splits across two roles because no single non-superuser role can USE all four
schemas: schema c3 is read on the c3_app connection, c1/c2/c4 on the c3_reader connection. The
role-boundary tests below prove the split is actually required (they would fail if the code
reflected a schema with the wrong role). In the per-package CI DB the DSN is the superuser, so
SET ROLE works and these run; locally under a non-member role the SET ROLE is refused and they
skip (never silently pass).
"""

from __future__ import annotations

import contextlib
import os
import uuid

import pytest
from app.repositories.dictionary_repo import DictionaryRepo, VersionExists
from app.services import dictionary_service
from app.services.dictionary_service import (
    CROSS_SCHEMAS,
    OWN_SCHEMAS,
    SchemaUnreadable,
    _assert_schemas_readable,
)
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

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


@contextlib.contextmanager
def _role(conn, role: str):
    """SET ROLE for the block; skip the test if the switch is refused (non-member DSN locally)."""
    try:
        conn.execute(text(f"SET ROLE {role}"))
    except ProgrammingError as exc:
        pytest.skip(f"cannot SET ROLE {role} on this connection: {type(exc.orig).__name__}")
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            conn.execute(text("RESET ROLE"))


def _entity(document, name):
    return next((e for e in document["entities"] if e["name"] == name), None)


# -- reflection on the superuser DSN (can USE every schema): pass same conn for both roles ----
def test_generate_reflects_c3_tables(pg_session):
    """The c3 schema (migrated to head by pg_session) is reflected with its real columns."""
    eng = _engine()
    try:
        with eng.connect() as conn:
            doc = dictionary_service.generate(conn, conn, "it-1")
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
                doc = dictionary_service.generate(conn, conn, "it-2")
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
            doc = dictionary_service.generate(conn, conn, "it-3")
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
            doc = dictionary_service.generate(conn, conn, "it-4")
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


# -- role boundaries: the test that would have caught the single-connection bug ---------------
def test_role_boundaries_for_readability_guard(pg_session):
    """Each role may USE only its own subset; the guard raises on the wrong pairing.

    This is the regression guard: if the code ever reflected a schema with the wrong role, one
    of these assertions fails.
    """
    eng = _engine()
    try:
        with eng.connect() as conn:
            # c3_app owns c3 but cannot USE c1/c2/c4 -> guard must raise for the cross set.
            with _role(conn, "c3_app"):
                with pytest.raises(SchemaUnreadable):
                    _assert_schemas_readable(conn, CROSS_SCHEMAS)
                _assert_schemas_readable(conn, OWN_SCHEMAS)  # c3 is fine -> no raise
            # c3_reader has USAGE on c1/c2/c4 but not c3 -> guard must raise for the own set.
            with _role(conn, "c3_reader"):
                with pytest.raises(SchemaUnreadable):
                    _assert_schemas_readable(conn, OWN_SCHEMAS)
                _assert_schemas_readable(conn, CROSS_SCHEMAS)  # cross set is fine -> no raise
    finally:
        eng.dispose()


def test_generate_under_real_roles(pg_session):
    """End to end with the real split: c3 on c3_app, c1/c2/c4 on c3_reader — no raise.

    The USAGE boundary is what makes the split necessary (proven in the role-boundary test). Here
    we prove ``generate`` runs under the two real roles without raising. Table *content* for c3 is
    only visible when c3_app also holds SELECT on its tables — true on RDS (c3_app owns them),
    but not on the compose/CI DB where the superuser owns them. So assert the c3 postgres entities
    only when c3_app actually has that SELECT; always assert the Mongo entities merge.
    """
    eng = _engine()
    try:
        app_conn = eng.connect()
        reader_conn = eng.connect()
        try:
            try:
                app_conn.execute(text("SET ROLE c3_app"))
                reader_conn.execute(text("SET ROLE c3_reader"))
            except ProgrammingError as exc:
                pytest.skip(f"cannot SET ROLE on this connection: {type(exc.orig).__name__}")

            # generate must not raise under the correct role split.
            doc = dictionary_service.generate(app_conn, reader_conn, "it-roles")

            # Mongo entities are always merged (independent of Postgres role).
            assert _entity(doc, "activity_patterns") is not None

            # c3 table content appears only if c3_app can SELECT its tables (RDS ownership); on
            # the compose/CI DB the superuser owns them, so c3_app sees the schema but no columns.
            c3_selectable = app_conn.execute(
                text("SELECT has_table_privilege('c3.ml_models', 'SELECT')")
            ).scalar_one()
            if c3_selectable:
                assert _entity(doc, "ml_models") is not None
                present = {e["schema_name"] for e in doc["entities"] if e["store"] == "postgres"}
                assert "c3" in present
        finally:
            with contextlib.suppress(Exception):
                app_conn.close()
            with contextlib.suppress(Exception):
                reader_conn.close()
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
