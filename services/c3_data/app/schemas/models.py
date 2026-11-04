"""Pydantic models for the model-management API (C3-07/08)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class LabelMapEntry(BaseModel):
    home_label: str
    category: str | None = None
    source_classes: list[str]
    min_confidence: float = Field(ge=0.0, le=1.0)
    rule: Literal["max", "mean", "consec2"]


class LabelMap(BaseModel):
    version: str | None = None
    entries: list[LabelMapEntry]


class ModelSummary(BaseModel):
    model_id: str
    name: str
    version: str
    status: str
    source: str
    metrics: dict[str, Any] | None = None
    created_at: datetime
    activated_at: datetime | None = None


class ModelDetail(ModelSummary):
    label_map: dict[str, Any]
    notes: str | None = None
    evaluations: list[dict[str, Any]] = Field(default_factory=list)


class CreateModelRequest(BaseModel):
    name: str = "yamnet"
    version: str
    base_model_id: str | None = None
    label_map: LabelMap | None = None
    notes: str | None = None


class EvaluateRequest(BaseModel):
    dataset: str = "eval-v1"


class ActivateRequest(BaseModel):
    confirm: bool = True


class ClassesResponse(BaseModel):
    classes: list[str]


class WorkerStatus(BaseModel):
    worker_id: str | None = None
    hostname: str | None = None
    model_id: str | None = None
    model_version: str | None = None
    last_heartbeat: datetime | None = None
    processed: int = 0
    failed: int = 0
    avg_latency_ms: float = 0


class QueueStatus(BaseModel):
    queued: int
    processing: int
    failed: int
    analyzed_last_hour: int


class DeploymentStatus(BaseModel):
    active_model: dict[str, Any] | None = None
    workers: list[WorkerStatus]
    queue: QueueStatus
    throughput_per_min: float
    p95_latency_ms: int
