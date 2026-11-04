"""Pydantic models for the inference endpoints (C3-05)."""

from __future__ import annotations

from pydantic import BaseModel


class ModelRef(BaseModel):
    model_id: str
    name: str
    version: str


class LabelOut(BaseModel):
    label: str
    confidence: float
    source_class: str
    start_s: float
    end_s: float


class RawScoreOut(BaseModel):
    class_name: str
    score: float


class TestClassifyResult(BaseModel):
    model: ModelRef
    top_label: str
    top_confidence: float
    labels: list[LabelOut]
    raw_top10: list[RawScoreOut]
    frames: int
    duration_s: float
    latency_ms: int
