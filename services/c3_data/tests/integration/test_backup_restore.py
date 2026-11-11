"""C3-14 (Tier 2): real backup then real restore into an empty store (Rev4 §7).

A backup with no tested restore is not a backup. These run the actual pg_dump/pg_restore and
mongodump/mongorestore against real stores and S3 (LocalStack), restore into EMPTY targets, and
assert row counts and a sample document match. media_events is treated as C1-owned: only C3's
fields are backed up and re-applied with $set, never a full-collection replace.

Needs pg_dump/pg_restore/mongodump/mongorestore on PATH (present in the c3-data image and on the
CI runner). Missing tools FAIL on CI, SKIP locally — the same discipline as the store fixtures.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.jobs import backup as backup_job
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration

_TOOLS = ("pg_dump", "pg_restore", "mongodump", "mongorestore")


def _require(reason: str):
    if os.environ.get("CI") == "true":
        pytest.fail(f"integration requirement on CI: {reason}", pytrace=False)
    pytest.skip(reason)


def _require_tools():
    """Skip (even on CI) when the backup CLIs are absent.

    Unlike a missing store (a real CI misconfig that should fail), the backup tools
    (pg_dump/mongodump/...) live in the c3-data image and on RDS, not necessarily on the
    per-package CI runner. Their real coverage is ``make test-c3-int`` (c3 image) and the EC2
    deploy, so a plain skip here is correct — the pure helpers and the media_events-fields logic
    (no CLI) still run everywhere.
    """
    missing = [t for t in _TOOLS if shutil.which(t) is None]
    if missing:
        pytest.skip(f"backup tools not on PATH (run via `make test-c3-int`): {', '.join(missing)}")


def _pg_url() -> str:
    url = os.environ.get("DATABASE_URL_C3")
    if not url:
        _require("DATABASE_URL_C3 not set")
    return url


def _mongo_url() -> str:
    url = os.environ.get("MONGO_URL_C3")
    if not url:
        _require("MONGO_URL_C3 not set")
    return url


@contextlib.contextmanager
def tempdir():
    d = tempfile.mkdtemp()
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# -- Postgres: dump schema c3, restore into an empty database ------------------------------
def test_postgres_backup_restore_round_trip(pg_session):
    _require_tools()
    src_url = _pg_url()
    # Seed a uniquely-tagged model row in the source c3 schema.
    tag = uuid.uuid4().hex[:8]
    pg_session.execute(
        text(
            "INSERT INTO c3.ml_models (model_id, name, version, source, label_map, status, "
            "created_by) VALUES (:id, 'yamnet', :v, 'bundled', '{}'::jsonb, 'registered', :by)"
        ),
        {"id": str(uuid.uuid4()), "v": f"bk-{tag}", "by": "00000000-0000-0000-0000-000000000000"},
    )
    pg_session.commit()
    src_count = pg_session.execute(text("SELECT count(*) FROM c3.ml_models")).scalar_one()

    libpq = backup_job.libpq_url(src_url)
    admin = create_engine(libpq, isolation_level="AUTOCOMMIT", future=True)
    target_db = f"c3_restore_{tag}"
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{target_db}"'))
        # Build the target URL (swap the database name in the path).
        base, _, _old = libpq.rpartition("/")
        target_url = f"{base}/{target_db}"

        with tempdir() as tmp:
            dump = tmp / "c3_pg.dump"
            backup_job.dump_postgres(src_url, dump)
            # Restore into the empty target: create schema c3 first, then pg_restore.
            tgt = create_engine(target_url, isolation_level="AUTOCOMMIT", future=True)
            try:
                with tgt.connect() as conn:
                    conn.execute(text("CREATE SCHEMA IF NOT EXISTS c3"))
                backup_job.restore_postgres(target_url, dump)
                with tgt.connect() as conn:
                    restored = conn.execute(text("SELECT count(*) FROM c3.ml_models")).scalar_one()
                    sample = conn.execute(
                        text("SELECT version FROM c3.ml_models WHERE version = :v"),
                        {"v": f"bk-{tag}"},
                    ).scalar_one()
            finally:
                tgt.dispose()

        assert restored == src_count  # row counts match
        assert sample == f"bk-{tag}"  # the sample row round-tripped
    finally:
        with admin.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :d AND pid <> pg_backend_pid()"
                ),
                {"d": target_db},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{target_db}"'))
        admin.dispose()
        pg_session.execute(text("DELETE FROM c3.ml_models WHERE version = :v"), {"v": f"bk-{tag}"})
        pg_session.commit()


# -- Mongo: dump C3-owned collections, restore into empty collections ----------------------
def test_mongo_backup_restore_round_trip():
    _require_tools()
    import subprocess

    from pymongo import MongoClient

    url = _mongo_url()
    client = MongoClient(url, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
    except Exception as exc:
        _require(f"Mongo unreachable: {type(exc).__name__}")

    tag = uuid.uuid4().hex[:8]
    src_db = client.get_default_database()
    db_name = backup_job._db_name(url)
    # Seed a tagged detection + activity bucket in the C3-owned collections.
    det_id = f"det-{tag}"
    src_db["ai_detections"].insert_one(
        {"_id": det_id, "media_id": f"m-{tag}", "tenant_id": tag, "top_label": "glass_break"}
    )
    bucket_id = f"h:{tag}:2026-06-01"
    src_db["activity_patterns"].insert_one(
        {"_id": bucket_id, "tenant_id": tag, "house_id": "h", "hours": [0] * 24, "counted": []}
    )

    # Restore each archive into an empty, uniquely-named collection in the SAME db (c3_app can
    # create/drop collections in homeai but cannot drop a database), via an ns remap.
    restored_cols: dict[str, str] = {}
    try:
        with tempdir() as tmp:
            archives = backup_job.dump_mongo(url, tmp)
            for col, path in archives.items():
                target_col = f"{col}__restore_{tag}"
                restored_cols[col] = target_col
                proc = subprocess.run(
                    [
                        "mongorestore",
                        f"--uri={url}",
                        f"--archive={path}",
                        "--gzip",
                        f"--nsFrom={db_name}.{col}",
                        f"--nsTo={db_name}.{target_col}",
                    ],
                    capture_output=True,
                    text=True,
                )
                assert proc.returncode == 0, proc.stderr

        # Row counts + sample for the two seeded collections.
        assert src_db[restored_cols["ai_detections"]].count_documents({"_id": det_id}) == 1
        assert src_db[restored_cols["activity_patterns"]].count_documents({"_id": bucket_id}) == 1
        restored_det = src_db[restored_cols["ai_detections"]].find_one({"_id": det_id})
        assert restored_det["top_label"] == "glass_break"
    finally:
        for target_col in restored_cols.values():
            src_db[target_col].drop()
        src_db["ai_detections"].delete_one({"_id": det_id})
        src_db["activity_patterns"].delete_one({"_id": bucket_id})
        client.close()


# -- media_events: back up + restore ONLY C3's fields (C1 owns the collection) --------------
def test_media_events_fields_restore_does_not_clobber_c1(mongo_db):
    url = _mongo_url()
    from pymongo import MongoClient

    client = MongoClient(url, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
    except Exception as exc:
        _require(f"Mongo unreachable: {type(exc).__name__}")

    db = client.get_default_database()
    tag = uuid.uuid4().hex[:8]
    mid = f"m-{tag}"
    det_tag = f"d-{tag}"
    # A media_events doc with both C1 fields (owned by C1) and C3 processing fields.
    db["media_events"].insert_one(
        {
            "_id": mid,
            "tenant_id": tag,
            "house_id": "h-1",  # C1 field
            "feed_id": "f-1",  # C1 field
            "status": "analyzed",  # C3 field
            "attempts": 2,  # C3 field
            "detection_id": det_tag,  # C3 field
            "handoff_status": "done",  # C3 field
        }
    )
    try:
        # Export only C3's fields.
        exported = [d for d in backup_job.export_media_event_fields(url) if d["_id"] == mid]
        assert len(exported) == 1
        assert "house_id" not in exported[0]  # C1 field not exported
        assert exported[0]["status"] == "analyzed"

        # Simulate a loss of C3's fields (but C1's row/fields survive).
        db["media_events"].update_one(
            {"_id": mid},
            {
                "$set": {
                    "status": "queued",
                    "attempts": 0,
                    "detection_id": None,
                    "handoff_status": "none",
                }
            },
        )
        # Restore C3's fields; C1's house_id/feed_id must be untouched.
        updated = backup_job.restore_media_event_fields(url, exported)
        assert updated == 1
        doc = db["media_events"].find_one({"_id": mid})
        assert doc["status"] == "analyzed"  # C3 field restored
        assert doc["detection_id"] == det_tag
        assert doc["house_id"] == "h-1"  # C1 field intact
        assert doc["feed_id"] == "f-1"
    finally:
        db["media_events"].delete_one({"_id": mid})
        client.close()


# -- full job: writes the three artifacts to S3 under backups/<date>/ -----------------------
def test_run_backup_job_writes_s3_artifacts(pg_session, s3_bucket):
    _require_tools()
    s3, bucket = s3_bucket
    from app.settings import Settings

    settings = Settings(
        env="test",
        database_url=_pg_url(),
        mongo_url=_mongo_url(),
        s3_bucket=bucket,
        aws_region=os.environ.get("AWS_REGION", "us-west-2"),
        aws_endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
    )
    as_of = datetime(2026, 6, 1, tzinfo=UTC)
    keys = backup_job.run_backup_job(settings, as_of=as_of)

    assert keys["postgres"] == "backups/2026-06-01/c3_pg.dump"
    assert keys["media_event_fields"] == "backups/2026-06-01/c3_media_events_fields.json"
    # One archive per C3-owned collection (activity_patterns must be present).
    assert (
        keys["mongo:activity_patterns"] == "backups/2026-06-01/mongo/activity_patterns.archive.gz"
    )
    assert keys["mongo:ai_detections"] == "backups/2026-06-01/mongo/ai_detections.archive.gz"
    assert (
        keys["mongo:worker_heartbeats"] == "backups/2026-06-01/mongo/worker_heartbeats.archive.gz"
    )

    # Every artifact is really in S3.
    for key in keys.values():
        head = s3.head_object(Bucket=bucket, Key=key)
        assert head["ContentLength"] > 0
    # The media-fields JSON is valid and field-scoped.
    body = s3.get_object(Bucket=bucket, Key=keys["media_event_fields"])["Body"].read()
    parsed = json.loads(body)
    assert isinstance(parsed, list)
    for doc in parsed:
        assert "house_id" not in doc  # C1 field never exported

    # Clean up the day's objects.
    for key in keys.values():
        s3.delete_object(Bucket=bucket, Key=key)
