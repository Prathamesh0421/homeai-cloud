"""Shared Tier 2 fixtures: real Postgres, Mongo, and LocalStack S3.

Generalizes the skip/fail guard from tests/mongo/test_detection_repo.py: a missing store FAILS
on CI (CI=true) and SKIPS locally with a clear message, so you can never quietly run these
against a fake. Every test in tests/integration/ is marked ``integration`` via this conftest.

Env (provided by CI and by ``make test-c3-int``):
    DATABASE_URL_C3, MONGO_URL_C3, S3_BUCKET, AWS_REGION, AWS_ENDPOINT_URL,
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

# Mark every test under tests/integration/ as integration.
pytestmark = pytest.mark.integration


def _require(reason: str) -> None:
    """FAIL on CI (a missing store is a CI misconfig), SKIP locally with a message."""
    if os.environ.get("CI") == "true":
        pytest.fail(f"integration store required on CI: {reason}", pytrace=False)
    pytest.skip(reason)


# --- PostgreSQL -----------------------------------------------------------
@pytest.fixture
def pg_url() -> str:
    url = os.environ.get("DATABASE_URL_C3")
    if not url:
        _require("DATABASE_URL_C3 not set")
    return url


@pytest.fixture
def pg_engine(pg_url: str):
    from sqlalchemy import create_engine, text

    engine = create_engine(pg_url, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # unreachable Postgres
        engine.dispose()
        _require(f"Postgres unreachable: {type(exc).__name__}")
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine) -> Iterator:
    """A session with the c3 schema migrated to head (idempotent per run)."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.orm import sessionmaker

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", str(pg_engine.url))
    command.upgrade(cfg, "head")

    factory = sessionmaker(bind=pg_engine, expire_on_commit=False, future=True)
    session = factory()
    yield session
    session.close()


# --- MongoDB --------------------------------------------------------------
@pytest.fixture
def mongo_db():
    """A real Mongo database handle on a throwaway namespace; collections dropped after."""
    url = os.environ.get("MONGO_URL_C3")
    if not url:
        _require("MONGO_URL_C3 not set")
    from pymongo import MongoClient

    client = MongoClient(url, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
    except Exception as exc:
        client.close()
        _require(f"Mongo unreachable: {type(exc).__name__}")

    db = client.get_default_database()
    created: list[str] = []

    class _TrackingDb:
        def __getitem__(self, name):
            uniq = f"{name}_it_{uuid.uuid4().hex[:8]}"
            created.append(uniq)
            return db[uniq]

        # Allow attribute-style access used by some helpers.
        def __getattr__(self, item):
            return getattr(db, item)

    yield _TrackingDb()
    for name in created:
        db[name].drop()
    client.close()


# --- S3 (LocalStack) ------------------------------------------------------
@pytest.fixture
def s3_bucket():
    """Ensure the configured bucket exists on LocalStack; returns (client, bucket)."""
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if not endpoint:
        _require("AWS_ENDPOINT_URL not set (LocalStack)")
    from homeai_common.s3 import s3_client

    region = os.environ.get("AWS_REGION", "us-west-2")
    bucket = os.environ.get("S3_BUCKET", "homeai-ci")
    client = s3_client(region, endpoint)
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:
        try:
            if region == "us-east-1":
                client.create_bucket(Bucket=bucket)
            else:
                client.create_bucket(
                    Bucket=bucket,
                    CreateBucketConfiguration={"LocationConstraint": region},
                )
        except Exception as exc:
            _require(f"S3/LocalStack unavailable: {type(exc).__name__}")
    return client, bucket
