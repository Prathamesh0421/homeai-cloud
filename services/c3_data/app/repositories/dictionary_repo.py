"""``data_dictionary_versions`` writer (Postgres, schema c3; C3-13).

Versions are immutable: ``version`` is the primary key, so publishing the same version twice
collides and is turned into a 409 by the router (via :class:`VersionExists`). The whole
generated document is stored as JSONB.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.orm import DataDictionaryVersion


class VersionExists(Exception):
    """A dictionary version with this id already exists (immutable PK collision)."""


class DictionaryRepo:
    def __init__(self, session: Session):
        self.session = session

    def publish(self, version: str, document: dict, published_by: str) -> DataDictionaryVersion:
        row = DataDictionaryVersion(version=version, document=document, published_by=published_by)
        self.session.add(row)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise VersionExists() from exc
        return row

    def get(self, version: str) -> DataDictionaryVersion | None:
        return self.session.get(DataDictionaryVersion, version)

    def latest(self) -> DataDictionaryVersion | None:
        stmt = (
            select(DataDictionaryVersion)
            .order_by(DataDictionaryVersion.published_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalars().first()

    def list_versions(self) -> list[DataDictionaryVersion]:
        stmt = select(DataDictionaryVersion).order_by(DataDictionaryVersion.published_at.desc())
        return list(self.session.execute(stmt).scalars())
