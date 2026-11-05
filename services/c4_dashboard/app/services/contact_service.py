"""Emergency contact service: CRUD, ordering, validation."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models.orm import EmergencyContact
from app.repositories import contact_repo
from app.schemas.settings import (
    ContactCreateRequest,
    ContactPatchRequest,
    ContactResponse,
)

MAX_CONTACTS = 5


def _to_response(c: EmergencyContact) -> ContactResponse:
    return ContactResponse(
        contact_id=str(c.contact_id),
        house_id=str(c.house_id),
        name=c.name,
        email=c.email,
        phone=c.phone,
        contact_type=c.contact_type,
        priority=c.priority,
    )


def list_contacts(session: Session, house_id: UUID) -> list[ContactResponse]:
    return [_to_response(c) for c in contact_repo.list_for_house(session, house_id)]


def create_contact(
    session: Session,
    *,
    house_id: UUID,
    tenant_id: UUID,
    payload: ContactCreateRequest,
) -> ContactResponse:
    if contact_repo.count_for_house(session, house_id) >= MAX_CONTACTS:
        raise ApiError(409, "contact_limit", f"max {MAX_CONTACTS} contacts per house")

    # email uniqueness within the house
    existing = session.scalars(
        select(EmergencyContact).where(
            EmergencyContact.house_id == house_id,
            EmergencyContact.email == payload.email,
        )
    ).first()
    if existing is not None:
        raise ApiError(409, "email_exists", "email already used for this house")

    priority = payload.priority
    if priority is None:
        priority = contact_repo.max_priority(session, house_id) + 1
    else:
        # inserting at an existing priority shifts others down
        rows = contact_repo.list_for_house(session, house_id)
        for r in rows:
            if r.priority >= priority:
                r.priority += 1

    contact = EmergencyContact(
        contact_id=uuid4(),
        house_id=house_id,
        tenant_id=tenant_id,
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        contact_type=payload.contact_type,
        priority=priority,
    )
    contact_repo.add(session, contact)
    session.commit()
    session.refresh(contact)
    return _to_response(contact)


def patch_contact(
    session: Session,
    *,
    contact_id: UUID,
    payload: ContactPatchRequest,
) -> ContactResponse:
    contact = contact_repo.get(session, contact_id)
    if contact is None:
        raise ApiError(404, "not_found", "contact not found")

    data = payload.model_dump(exclude_unset=True)

    if "email" in data and data["email"] != contact.email:
        clash = session.scalars(
            select(EmergencyContact).where(
                EmergencyContact.house_id == contact.house_id,
                EmergencyContact.email == data["email"],
                EmergencyContact.contact_id != contact.contact_id,
            )
        ).first()
        if clash is not None:
            raise ApiError(409, "email_exists", "email already used for this house")
        contact.email = data["email"]

    if "name" in data:
        contact.name = data["name"]
    if "phone" in data:
        contact.phone = data["phone"]
    if "contact_type" in data:
        contact.contact_type = data["contact_type"]
    if "priority" in data and data["priority"] is not None:
        # shift others at/after the new priority down, then set
        rows = contact_repo.list_for_house(session, contact.house_id)
        for r in rows:
            if r.contact_id == contact.contact_id:
                continue
            if r.priority >= data["priority"]:
                r.priority += 1
        contact.priority = data["priority"]

    session.commit()
    session.refresh(contact)
    return _to_response(contact)


def delete_contact(session: Session, *, contact_id: UUID) -> None:
    contact = contact_repo.get(session, contact_id)
    if contact is None:
        raise ApiError(404, "not_found", "contact not found")
    house_id = contact.house_id
    contact_repo.delete(session, contact)
    session.commit()
    contact_repo.compact_priorities(session, house_id)
    session.commit()


def reorder_contacts(
    session: Session,
    *,
    house_id: UUID,
    contact_ids: list[str],
) -> None:
    rows = contact_repo.list_for_house(session, house_id)
    existing_ids = {str(r.contact_id) for r in rows}
    submitted = set(contact_ids)

    if submitted != existing_ids or len(contact_ids) != len(submitted):
        raise ApiError(
            422,
            "reorder_mismatch",
            "must list every contact id exactly once",
            {"expected": sorted(existing_ids), "got": sorted(submitted)},
        )

    ordered = [UUID(cid) for cid in contact_ids]
    contact_repo.reorder(session, house_id, ordered)
    session.commit()
