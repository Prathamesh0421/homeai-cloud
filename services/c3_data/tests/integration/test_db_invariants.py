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


def test_evaluating_the_active_model_keeps_it_active(pg_session):
    """set_metrics must not demote the active model (regression: evaluating un-activated it).

    Evaluating an already-active model previously set status='evaluated', de-activating the live
    deployment. Now set_metrics only promotes registered -> evaluated and leaves active/retired
    alone, while still storing the metrics. Proven on real Postgres so the one-active invariant
    (ux_one_active) is exercised, not a SQLite stand-in.
    """
    from app.repositories.ml_model_repo import MlModelRepo

    pg_session.execute(text("DELETE FROM c3.ml_models"))
    pg_session.commit()
    repo = MlModelRepo(pg_session)
    try:
        active = _model("9.2.0", "active")
        registered = _model("9.3.0", "registered")
        pg_session.add_all([active, registered])
        pg_session.commit()

        # Evaluate the ACTIVE model: metrics stored, status stays active.
        repo.set_metrics(active, {"accuracy": 1.0})
        pg_session.commit()
        assert active.status == "active"
        assert active.metrics == {"accuracy": 1.0}

        # Evaluate a REGISTERED model: it is promoted to evaluated.
        repo.set_metrics(registered, {"accuracy": 0.9})
        pg_session.commit()
        assert registered.status == "evaluated"

        # The one-active invariant still holds: exactly one active row, and it is 9.2.0.
        n_active = pg_session.execute(
            text("SELECT count(*) FROM c3.ml_models WHERE status='active'")
        ).scalar_one()
        assert n_active == 1
        assert repo.get_active().version == "9.2.0"
    finally:
        pg_session.execute(text("DELETE FROM c3.ml_models WHERE version IN ('9.2.0','9.3.0')"))
        pg_session.commit()
