"""Request/response models for the data dictionary (C3-13, docs §3.2, §4.7)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, model_validator


class GenerateRequest(BaseModel):
    """``POST /data-dictionary``: either generate from the live schema, or publish a document.

    ``{version, generate: true}`` reflects the live Postgres schemas + Mongo shapes.
    ``{version, document}`` publishes a supplied document (rare; generate is the normal path).
    """

    version: str
    generate: bool = False
    document: dict | None = None

    @model_validator(mode="after")
    def _one_of(self) -> GenerateRequest:
        if not self.generate and self.document is None:
            raise ValueError("either generate=true or a document must be provided")
        return self


class FieldOut(BaseModel):
    name: str
    type: str
    nullable: bool | None = None
    internal: bool = False
    description: str | None = None


class EntityOut(BaseModel):
    name: str
    store: str  # "postgres" or "mongo"
    schema_name: str | None = None  # Postgres schema (c1..c4); None for Mongo
    owner_component: str  # c1 / c2 / c3 / c4
    fields: list[FieldOut]


class DictionaryDocument(BaseModel):
    version: str
    generated_at: datetime
    entities: list[EntityOut]


class DictionaryVersionOut(BaseModel):
    version: str
    published_by: str
    published_at: datetime
    document: DictionaryDocument
