"""Read access to ``c3.ml_models`` (C3-05 slice; full CRUD lands in C3-07).

Phase 4 only needs to fetch the active model and a model by id so the test-classify endpoint
can resolve a label map. Lifecycle mutations (create/activate/retire) come in Phase 6.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import MlModel


class MlModelRepo:
    def __init__(self, session: Session):
        self.session = session

    def get_active(self) -> MlModel | None:
        return self.session.scalars(select(MlModel).where(MlModel.status == "active")).one_or_none()

    def get(self, model_id: str) -> MlModel | None:
        return self.session.get(MlModel, model_id)
