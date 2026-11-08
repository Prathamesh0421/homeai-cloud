"""Pydantic models for records and stats (C3-10)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class StatBucket(BaseModel):
    key: str
    count: int


class RecordItem(BaseModel):
    # Records are heterogeneous across entities; expose as an open object.
    model_config = {"extra": "allow"}


# A record is returned as a plain dict (shape varies by entity); typed as dict in routes.
Record = dict[str, Any]
