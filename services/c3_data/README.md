# C3 — System Database Management and AI Inference

C3 runs the YAMNet inference pipeline, the model registry, record browsing, the data
dictionary, integrity checks, activity patterns, and the nightly backup. See
`docs/components/C3_DATABASE_AND_AI.md` for the full design.

## Backup and restore (C3-14)

C3 backs up its own stores nightly and on demand, and the restore is tested, not assumed.

### What is backed up

Written to S3 under `backups/<yyyy-mm-dd>/`:

| Artifact | Contents | Tool |
|---|---|---|
| `c3_pg.dump` | Postgres **schema `c3`** (`ml_models`, `model_evaluations`, `integrity_reports`, `data_dictionary_versions`) | `pg_dump -Fc -n c3` |
| `mongo/<collection>.archive.gz` | One archive per **C3-owned** Mongo collection: `ai_detections`, `activity_patterns`, `worker_heartbeats` | `mongodump -d homeai -c <col> --gzip` |
| `c3_media_events_fields.json` | **Only C3's fields** of the C1-owned `media_events`, keyed by `_id` | scripted export |

`activity_patterns` is the newest C3 collection and the easy one to miss — it is explicitly in
the dump list.

### media_events is C1-owned (cross-component boundary)

C1 owns the `media_events` collection and is responsible for a full restore of it. C3 only
writes the processing fields (`status`, `attempts`, `claimed_at`, `worker_id`, `error`,
`detection_id`, `handoff_status`) and so backs up and restores **only those fields**, applied
with `$set` keyed by `_id` — never a full-collection replace, so a C3 restore never clobbers
C1's fields. If `media_events` itself is lost, C1 restores the collection first; C3 then
re-applies its processing fields from `c3_media_events_fields.json`.

### Schedule and on-demand

- Nightly: the one C3 scheduler (in the worker) runs the backup at `C3_BACKUP_JOB_HOUR`
  (default 04:00 UTC), after the baseline (02:00) and integrity (03:00) jobs.
- On demand: `make backup-run` (or `python -m app.jobs.backup` inside the image).

### Credentials and the `%`-password rule

`pg_dump`/`mongodump` receive the **full connection URI unchanged**, so libpq and the Mongo
driver decode any percent-encoding (e.g. a `%` in a Secrets Manager password). We never extract
the password or set `PGPASSWORD` to a still-encoded value, and never `%%`-escape here — that
escape is only for Alembic's ConfigParser, not these tools. (The only transform is stripping the
SQLAlchemy `+psycopg` driver suffix so `pg_dump` gets a plain libpq URL.)

### Restore (proven by a test)

A backup with no tested restore is not a backup; `tests/integration/test_backup_restore.py`
runs a real backup then a real restore into an empty store and asserts row counts and a sample
document match. To restore by hand from an S3 backup:

```sh
# 1. Fetch the day's artifacts from S3.
aws s3 cp "s3://$S3_BUCKET/backups/<date>/c3_pg.dump" .
aws s3 cp "s3://$S3_BUCKET/backups/<date>/c3_mongo.archive.gz" .
aws s3 cp "s3://$S3_BUCKET/backups/<date>/c3_media_events_fields.json" .

# 2. Restore Postgres schema c3 (pass the URI so a % password decodes; strip +psycopg).
pg_restore --clean --if-exists --no-owner -n c3 \
  -d "postgresql://c3_app:...@<host>:5432/homeai" c3_pg.dump

# 3. Restore each C3-owned Mongo collection (one archive per collection; --drop replaces it).
for col in ai_detections activity_patterns worker_heartbeats; do
  mongorestore --uri "mongodb://c3_app:...@<host>:27017/homeai?authSource=homeai" \
    --archive="mongo/$col.archive.gz" --gzip --drop
done

# 4. Re-apply C3's media_events fields only (after C1 has restored the collection).
python -m app.jobs.restore_media_events c3_media_events_fields.json   # or via the test helper
```

The programmatic entry points are `app.jobs.backup.restore_postgres`,
`restore_mongo`, and `restore_media_event_fields`.
