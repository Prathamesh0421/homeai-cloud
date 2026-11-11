"""Nightly + on-demand backup of C3's stores, proven by restore (C3-14, docs §4.9, Rev4 §7).

What is backed up, and who owns it:
  - Postgres schema ``c3`` (ml_models, model_evaluations, integrity_reports,
    data_dictionary_versions) via ``pg_dump -Fc -n c3``.
  - The C3-owned Mongo collections ``ai_detections``, ``activity_patterns`` and
    ``worker_heartbeats`` via ``mongodump --gzip`` (``activity_patterns`` is the newest and the
    easy one to miss — it is explicitly in the list).
  - **Only C3's fields of the C1-owned ``media_events``** (``status``, ``attempts``,
    ``claimed_at``, ``worker_id``, ``error``, ``detection_id``, ``handoff_status``), exported as
    JSON keyed by ``_id``. C1 owns the collection; a full ``media_events`` restore is C1's
    responsibility. C3 restores its processing fields with ``$set`` by ``_id`` so it never
    clobbers C1's fields. (Rev4 §7 / §11 cross-component boundary.)

Credentials: the tools get the full connection URI unchanged, so libpq (pg_dump/pg_restore) and
the Mongo driver (mongodump/mongorestore) decode any percent-encoding (e.g. a ``%`` in a Secrets
Manager password). We never extract the password or set ``PGPASSWORD`` to a still-encoded value,
and never ``%%``-escape here (that escape is only for Alembic's ConfigParser, not these tools).

Artifacts land in S3 at ``backups/<yyyy-mm-dd>/``: ``c3_pg.dump``, one
``mongo/<collection>.archive.gz`` per C3-owned collection, and
``c3_media_events_fields.json``. A backup with no tested restore is not a backup, so
``restore_*`` and the integration test round-trip real archives into an empty store.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from homeai_common.mongo import get_mongo_db
from homeai_common.s3 import s3_client

from app.settings import Settings

logger = logging.getLogger("c3.backup")

PG_SCHEMA = "c3"
# C3-owned Mongo collections (app/db/mongo_indexes.py). activity_patterns is the newest; keep it.
C3_COLLECTIONS = ["ai_detections", "activity_patterns", "worker_heartbeats"]
# C3's fields on the C1-owned media_events (app/repositories/media_event_repo.py).
MEDIA_EVENT_C3_FIELDS = [
    "status",
    "attempts",
    "claimed_at",
    "worker_id",
    "error",
    "detection_id",
    "handoff_status",
]

PG_DUMP_NAME = "c3_pg.dump"
MEDIA_FIELDS_NAME = "c3_media_events_fields.json"


class BackupToolMissing(RuntimeError):
    """pg_dump / mongodump (or their restore counterparts) is not on PATH."""


def libpq_url(database_url: str) -> str:
    """Strip the SQLAlchemy ``+driver`` so pg_dump/pg_restore get a plain libpq URI.

    ``postgresql+psycopg://...`` -> ``postgresql://...``. Credentials (and any percent-encoding)
    are left untouched so libpq decodes them.
    """
    scheme, sep, rest = database_url.partition("://")
    if not sep:
        return database_url
    base = scheme.split("+", 1)[0]  # postgresql+psycopg -> postgresql
    return f"{base}://{rest}"


def _require_tools(*tools: str) -> None:
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        raise BackupToolMissing(f"required tool(s) not on PATH: {', '.join(missing)}")


def _run(cmd: list[str], **kwargs) -> None:
    """Run a subprocess, raising with captured stderr on failure (never logs the URI)."""
    proc = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if proc.returncode != 0:
        # cmd[0] only — the argv may contain a connection URI with credentials.
        raise RuntimeError(f"{cmd[0]} failed ({proc.returncode}): {proc.stderr.strip()[:500]}")


# -- dump / export ----------------------------------------------------------------------------
def dump_postgres(database_url: str, out_path: Path) -> None:
    """pg_dump schema c3 in custom format (restorable with pg_restore)."""
    _require_tools("pg_dump")
    _run(["pg_dump", libpq_url(database_url), "-n", PG_SCHEMA, "-Fc", "-f", str(out_path)])


def dump_mongo(mongo_url: str, out_dir: Path) -> dict[str, Path]:
    """mongodump each C3-owned collection to its own gzip archive in ``out_dir``.

    One archive per collection (``mongodump -d <db> -c <collection> --archive=...``); mongodump
    cannot select several named collections in a single invocation, and per-collection archives
    also make a selective restore clean. media_events is deliberately excluded (C1 owns it).
    Returns {collection: archive_path}.
    """
    _require_tools("mongodump")
    db_name = _db_name(mongo_url)
    archives: dict[str, Path] = {}
    for col in C3_COLLECTIONS:
        path = out_dir / f"{col}.archive.gz"
        _run(
            [
                "mongodump",
                f"--uri={mongo_url}",
                "-d",
                db_name,
                "-c",
                col,
                f"--archive={path}",
                "--gzip",
            ]
        )
        archives[col] = path
    return archives


def export_media_event_fields(mongo_url: str) -> list[dict]:
    """Export only C3's fields of each media_events doc, keyed by _id (C1 owns the collection)."""
    db = get_mongo_db(mongo_url)
    projection = dict.fromkeys(MEDIA_EVENT_C3_FIELDS, 1)  # _id included by default
    docs = []
    for doc in db["media_events"].find({}, projection):
        docs.append({k: _jsonable(v) for k, v in doc.items()})
    return docs


# -- backup -----------------------------------------------------------------------------------
def run_backup_job(settings: Settings, mongo_db=None, *, as_of: datetime | None = None) -> dict:
    """Back up Postgres + Mongo to S3 under backups/<date>/. Returns the written S3 keys.

    ``mongo_db`` is accepted for a uniform scheduler signature but backup shells out to the CLI
    tools with the URI, so it uses ``settings.mongo_url`` directly.
    """
    if not settings.database_url or not settings.mongo_url:
        raise RuntimeError("backup needs DATABASE_URL_C3 and MONGO_URL_C3")
    as_of = (as_of or datetime.now(UTC)).astimezone(UTC)
    date = f"{as_of:%Y-%m-%d}"
    prefix = f"backups/{date}"
    client = s3_client(settings.aws_region, settings.aws_endpoint)

    keys: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        pg_file = tmp_path / PG_DUMP_NAME
        dump_postgres(settings.database_url, pg_file)
        keys["postgres"] = _upload(client, settings.s3_bucket, f"{prefix}/{PG_DUMP_NAME}", pg_file)

        archives = dump_mongo(settings.mongo_url, tmp_path)
        for col, path in archives.items():
            keys[f"mongo:{col}"] = _upload(
                client, settings.s3_bucket, f"{prefix}/mongo/{col}.archive.gz", path
            )

        media = export_media_event_fields(settings.mongo_url)
        media_file = tmp_path / MEDIA_FIELDS_NAME
        media_file.write_text(json.dumps(media))
        keys["media_event_fields"] = _upload(
            client, settings.s3_bucket, f"{prefix}/{MEDIA_FIELDS_NAME}", media_file
        )

    logger.info("backup complete", extra={"prefix": prefix, "collections": C3_COLLECTIONS})
    return keys


# -- restore ----------------------------------------------------------------------------------
# GUC SETs a newer pg_dump may emit that an older server rejects — cosmetic, data still
# restores. pg_restore reports these as "errors ignored on restore" and exits non-zero, so we
# distinguish them from real restore errors.
_IGNORABLE_RESTORE_ERRORS = ("unrecognized configuration parameter",)


def restore_postgres(database_url: str, dump_path: Path) -> None:
    """pg_restore the c3 schema dump into the target (schema must already be creatable).

    Tolerates the benign client/server version-skew GUC warnings (e.g. a v17 ``pg_dump`` emits
    ``SET transaction_timeout`` that a v16 server rejects): pg_restore ignores them and the data
    still lands, but it exits non-zero, so we only fail on a real error.
    """
    _require_tools("pg_restore")
    # --clean --if-exists so a re-restore over an existing schema is idempotent.
    proc = subprocess.run(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "-n",
            PG_SCHEMA,
            "-d",
            libpq_url(database_url),
            str(dump_path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        stderr = proc.stderr or ""
        real_errors = [
            line
            for line in stderr.splitlines()
            if "error:" in line.lower()
            and not any(ig in line for ig in _IGNORABLE_RESTORE_ERRORS)
            and "errors ignored on restore" not in line
        ]
        if real_errors:
            raise RuntimeError(f"pg_restore failed: {' | '.join(real_errors)[:500]}")
        logger.info("pg_restore completed with ignorable version-skew warnings")


def restore_mongo(mongo_url: str, archives: dict[str, Path]) -> None:
    """mongorestore each C3-owned collection archive (drops the collection first)."""
    _require_tools("mongorestore")
    for _col, path in archives.items():
        _run(
            [
                "mongorestore",
                f"--uri={mongo_url}",
                f"--archive={path}",
                "--gzip",
                "--drop",  # replace the C3-owned collection with the backed-up contents
            ]
        )


def restore_media_event_fields(mongo_url: str, docs: list[dict]) -> int:
    """Re-apply C3's media_events fields with $set by _id — never clobbers C1's fields.

    Returns the number of documents updated. Docs whose _id is not present are skipped (C1 owns
    the row; C3 only restores its own contributions where the row exists).
    """
    db = get_mongo_db(mongo_url)
    updated = 0
    for doc in docs:
        _id = doc.get("_id")
        if _id is None:
            continue
        fields = {k: doc[k] for k in MEDIA_EVENT_C3_FIELDS if k in doc}
        if not fields:
            continue
        res = db["media_events"].update_one({"_id": _id}, {"$set": fields})
        updated += res.modified_count
    return updated


# -- helpers ----------------------------------------------------------------------------------
def _db_name(mongo_url: str) -> str:
    from pymongo.uri_parser import parse_uri

    return parse_uri(mongo_url).get("database") or "homeai"


def _upload(client, bucket: str, key: str, path: Path) -> str:
    client.upload_file(str(path), bucket, key)
    return key


def _jsonable(value):
    """Make a Mongo value JSON-serialisable (datetimes -> ISO Z)."""
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return value


def main(argv: list[str] | None = None) -> int:
    """``python -m app.jobs.backup`` — run a backup now (on-demand)."""
    import argparse

    from homeai_common.logging import configure_logging

    parser = argparse.ArgumentParser(description="Run a C3 backup to S3 now.")
    parser.add_argument("--as-of", default=None, help="ISO-8601 UTC date to label the backup.")
    args = parser.parse_args(argv)

    settings = Settings()
    configure_logging("c3-backup", settings.log_level)
    if not settings.database_url or not settings.mongo_url:
        print("ERROR: DATABASE_URL_C3 and MONGO_URL_C3 must be set", file=sys.stderr)
        return 1
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else None
    keys = run_backup_job(settings, as_of=as_of)
    print(f"[backup] wrote: {', '.join(keys.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
