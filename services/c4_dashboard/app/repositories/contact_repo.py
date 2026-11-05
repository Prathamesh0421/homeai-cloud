"""Repository for emergency contacts."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import EmergencyContact


def list_for_house(session: Session, house_id: UUID) -> list[EmergencyContact]:
    stmt = (
        select(EmergencyContact)
        .where(EmergencyContact.house_id == house_id)
        .order_by(EmergencyContact.priority)
    )
    return list(session.scalars(stmt))


def get(session: Session, contact_id: UUID) -> EmergencyContact | None:
    return session.get(EmergencyContact, contact_id)


def count_for_house(session: Session, house_id: UUID) -> int:
    stmt = select(EmergencyContact).where(EmergencyContact.house_id == house_id)
    return len(list(session.scalars(stmt)))


def max_priority(session: Session, house_id: UUID) -> int:
    rows = list_for_house(session, house_id)
    return max((r.priority for r in rows), default=0)


def add(session: Session, contact: EmergencyContact) -> EmergencyContact:
    session.add(contact)
    return contact


def delete(session: Session, contact: EmergencyContact) -> None:
    session.delete(contact)


def reorder(session: Session, house_id: UUID, ordered_ids: list[UUID]) -> None:
    """Assign priorities 1..n in the given order. Caller validates the id set."""
    rows = {c.contact_id: c for c in list_for_house(session, house_id)}
    for index, cid in enumerate(ordered_ids, start=1):
        if cid in rows:
            rows[cid].priority = index


def compact_priorities(session: Session, house_id: UUID) -> None:
    rows = list_for_house(session, house_id)
    for index, row in enumerate(rows, start=1):
        row.priority = index
