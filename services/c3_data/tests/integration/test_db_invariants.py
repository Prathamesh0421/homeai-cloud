"""Tier 2: DB invariants that only real Postgres enforces (not SQLite).

The ``ux_one_active`` partial unique index is the real guarantee behind "only one active model"
(C3-08). SQLite ignores schemas and partial indexes, so this must run on Postgres.
"""

from __future__ import annotations

import uuid

import pytest
from app.models.orm import MlModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _model(version: str, status: str) -> MlModel:
    return MlModel(
        model_id=str(uuid.uuid4()),
        name="yamnet",
        version=version,
        source="bundled",
        label_map={"version": version, "entries": []},
        status=status,
        created_by="00000000-0000-0000-0000-000000000000",
    )


def test_second_active_model_is_rejected(pg_session):
    # Start from a clean c3.ml_models for this assertion.
    pg_session.execute(text("DELETE FROM c3.ml_models"))
    pg_session.commit()

    pg_session.add(_model("9.0.0", "active"))
    pg_session.commit()

    pg_session.add(_model("9.1.0", "active"))
    with pytest.raises(IntegrityError):
        pg_session.commit()
    pg_session.rollback()

    # Cleanup so the shared database is left tidy for other tests.
    pg_session.execute(text("DELETE FROM c3.ml_models WHERE version IN ('9.0.0','9.1.0')"))
    pg_session.commit()
