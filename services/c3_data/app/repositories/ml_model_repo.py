"""CRUD + lifecycle for ``c3.ml_models`` (C3-07).

Activation is a single transaction: the previous active row goes to ``retired`` and the target
row to ``active``. The ``ux_one_active`` partial unique index is the safety net — if two
activations race, the second commit fails on the unique constraint rather than leaving two
active rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import MlModel, ModelEvaluation


class MlModelRepo:
    def __init__(self, session: Session):
        self.session = session

    # -- reads --------------------------------------------------------------
    def get(self, model_id: str) -> MlModel | None:
        return self.session.get(MlModel, model_id)

    def get_active(self) -> MlModel | None:
        return self.session.scalars(select(MlModel).where(MlModel.status == "active")).one_or_none()

    def get_by_name_version(self, name: str, version: str) -> MlModel | None:
        return self.session.scalars(
            select(MlModel).where(MlModel.name == name, MlModel.version == version)
        ).one_or_none()

    def list(self, *, name: str | None = None, status: str | None = None) -> list[MlModel]:
        stmt = select(MlModel)
        if name:
            stmt = stmt.where(MlModel.name == name)
        if status:
            stmt = stmt.where(MlModel.status == status)
        stmt = stmt.order_by(MlModel.created_at.desc())
        return list(self.session.scalars(stmt))

    def evaluations_for(self, model_id: str) -> list[ModelEvaluation]:
        return list(
            self.session.scalars(
                select(ModelEvaluation)
                .where(ModelEvaluation.model_id == model_id)
                .order_by(ModelEvaluation.started_at.desc())
            )
        )

    # -- writes -------------------------------------------------------------
    def create(
        self,
        *,
        name: str,
        version: str,
        label_map: dict[str, Any],
        created_by: str,
        source: str = "bundled",
        notes: str | None = None,
    ) -> MlModel:
        model = MlModel(
            model_id=str(uuid.uuid4()),
            name=name,
            version=version,
            framework="tensorflow",
            source=source,
            label_map=label_map,
            status="registered",
            notes=notes,
            created_by=created_by,
        )
        self.session.add(model)
        self.session.flush()
        return model

    def update_label_map(self, model: MlModel, label_map: dict[str, Any]) -> MlModel:
        model.label_map = label_map
        model.status = "registered"  # editing invalidates a prior evaluation
        self.session.flush()
        return model

    def set_metrics(self, model: MlModel, metrics: dict[str, Any]) -> None:
        model.metrics = metrics
        model.status = "evaluated"
        self.session.flush()

    def add_evaluation(
        self,
        *,
        model_id: str,
        dataset: str,
        metrics: dict[str, Any],
        started_at: datetime,
        finished_at: datetime,
        created_by: str,
    ) -> ModelEvaluation:
        ev = ModelEvaluation(
            evaluation_id=str(uuid.uuid4()),
            model_id=model_id,
            dataset=dataset,
            metrics=metrics,
            started_at=started_at,
            finished_at=finished_at,
            created_by=created_by,
        )
        self.session.add(ev)
        self.session.flush()
        return ev

    def activate(self, model: MlModel, *, activated_by: str) -> None:
        """Swap the active model in one transaction (previous active -> retired)."""
        current = self.get_active()
        if current is not None and current.model_id != model.model_id:
            current.status = "retired"
            self.session.flush()  # clear the partial unique index before setting the new active
        model.status = "active"
        model.activated_by = activated_by
        model.activated_at = datetime.now(UTC)
        self.session.flush()

    def retire(self, model: MlModel) -> None:
        model.status = "retired"
        self.session.flush()
