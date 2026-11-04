"""Model lifecycle business logic (C3-07, docs §3.1).

Enforces the state machine:
  create        -> clone label map from base (default: active), validate, status=registered
  update_label_map -> 409 model_active if active; validate; status back to registered
  activate      -> require evaluated or retired (422 otherwise); swap active in a transaction
  retire        -> 409 if active

Validation checks every source class in a label map against YAMNet's 521 display names.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeai_common.errors import ApiError

from app.ml.label_mapper import LabelMapValidationError, validate_label_map
from app.ml.yamnet_runner import load_class_names
from app.models.orm import MlModel
from app.repositories.ml_model_repo import MlModelRepo


def bundled_class_names(model_dir: str) -> list[str]:
    """Read the 521 YAMNet class names from the bundled class map CSV (no TF load)."""
    csv = Path(model_dir) / "yamnet" / "1" / "yamnet_class_map.csv"
    return load_class_names(csv)


class ModelRegistry:
    def __init__(self, repo: MlModelRepo, class_names: list[str]):
        self.repo = repo
        self.class_names = class_names

    def _validate(self, label_map: dict[str, Any]) -> None:
        try:
            validate_label_map(label_map, self.class_names)
        except LabelMapValidationError as exc:
            raise ApiError(
                422,
                "validation_error",
                "label map references unknown YAMNet classes",
                details=[{"field": "source_classes", "issue": c} for c in exc.unknown],
            ) from exc

    def create_version(
        self,
        *,
        name: str,
        version: str,
        created_by: str,
        base_model_id: str | None = None,
        label_map: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> MlModel:
        if self.repo.get_by_name_version(name, version) is not None:
            raise ApiError(409, "invalid_state", f"version {name} {version} already exists")

        if label_map is None:
            base = self.repo.get(base_model_id) if base_model_id else self.repo.get_active()
            if base is None:
                raise ApiError(422, "validation_error", "no base model to clone a label map from")
            label_map = base.label_map

        self._validate(label_map)
        return self.repo.create(
            name=name, version=version, label_map=label_map, created_by=created_by, notes=notes
        )

    def update_label_map(self, model_id: str, label_map: dict[str, Any]) -> MlModel:
        model = self._require(model_id)
        if model.status == "active":
            raise ApiError(
                409, "model_active", "cannot edit the active model; create a new version"
            )
        self._validate(label_map)
        return self.repo.update_label_map(model, label_map)

    def activate(self, model_id: str, *, activated_by: str) -> MlModel:
        model = self._require(model_id)
        if model.status not in ("evaluated", "retired"):
            raise ApiError(
                422,
                "validation_error",
                "model must be evaluated or retired before activation",
                details={"status": model.status},
            )
        self.repo.activate(model, activated_by=activated_by)
        return model

    def retire(self, model_id: str) -> MlModel:
        model = self._require(model_id)
        if model.status == "active":
            raise ApiError(409, "invalid_state", "cannot retire the active model")
        self.repo.retire(model)
        return model

    def _require(self, model_id: str) -> MlModel:
        model = self.repo.get(model_id)
        if model is None:
            raise ApiError(404, "not_found", "model not found")
        return model
