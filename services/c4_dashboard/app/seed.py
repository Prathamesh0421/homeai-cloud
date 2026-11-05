"""Idempotent C4 seed data (C4-15).

Writes tenants, users, house service settings, emergency contacts and service
clients using the fixed IDs from ``scripts/seed_ids.py``. Run via::

    python -m app.seed            # uses app.settings + DATABASE_URL_C4
    make seed-c4

All upserts are idempotent: re-running updates fields in place without
creating duplicates. User passwords default to ``Demo!2026``; service client
secrets are read from environment variables
(``SERVICE_CLIENT_SECRET_<UPPER_DASHES>``) and fall back to a dev secret.
"""

from __future__ import annotations

import os

# scripts/seed_ids.py lives at the repo root and is importable when the worker
# runs from services/c4_dashboard (the Makefile adds the repo root to PYTHONPATH).
import sys
from uuid import UUID

import bcrypt
from sqlalchemy.orm import Session

from app.db.session import BASE_METADATA, session_scope
from app.models.orm import (
    EmergencyContact,
    HouseServiceSetting,
    ServiceClient,
    Tenant,
    User,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.seed_ids import HOUSES, MAPLE_CONTACTS, SERVICE_CLIENTS, TENANTS, USERS  # noqa: E402

DEFAULT_PASSWORD = "Demo!2026"
ALL_SERVICES = [
    "fire_safety",
    "distress",
    "intrusion",
    "fall",
    "wellness",
    "presence",
    "pet",
]

# Default scopes per service client (mirrors docs/02_CONTRACTS.md §2.5).
SERVICE_CLIENT_SCOPES: dict[str, list[str]] = {
    "c2-alerts": ["alerts:evaluate"],
    "c3-worker": ["clips:read", "classifications:write"],
    "c3-data": ["clips:read", "classifications:write", "models:read"],
    "c4-dashboard": ["users:read", "tenants:read"],
    "device-uploader": ["clips:write"],
}


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _ensure_schema() -> None:
    """Create the c4 schema, citext extension and tables if missing.

    In production Alembic owns the schema; this is a convenience for local dev
    and the Makefile ``seed-c4`` target so a fresh checkout can seed without
    running migrations first. Idempotent.
    """
    from sqlalchemy import text

    from app.db.session import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS c4"))
    BASE_METADATA.create_all(engine, checkfirst=True)


def _client_secret(client_id: str) -> str:
    env_key = "SERVICE_CLIENT_SECRET_" + client_id.upper().replace("-", "_")
    return os.environ.get(env_key, f"dev-{client_id}-secret")


def _upsert_tenant(session: Session, alias: str, tenant_id: UUID, name: str, tz: str) -> None:
    existing = session.get(Tenant, tenant_id)
    if existing is None:
        session.add(Tenant(tenant_id=tenant_id, name=name, timezone=tz, status="active"))
    else:
        existing.name = name
        existing.timezone = tz
        existing.status = "active"


def _upsert_user(
    session: Session,
    *,
    user_id: UUID,
    tenant_id: UUID | None,
    email: str,
    role: str,
    house_ids: list[UUID],
    password: str = DEFAULT_PASSWORD,
) -> None:
    existing = session.get(User, user_id)
    if existing is None:
        session.add(
            User(
                user_id=user_id,
                tenant_id=tenant_id,
                email=email,
                password_hash=_hash(password),
                role=role,
                house_ids=house_ids,
                is_active=True,
            )
        )
    else:
        existing.tenant_id = tenant_id
        existing.email = email
        existing.role = role
        existing.house_ids = house_ids
        existing.is_active = True


def _upsert_settings(
    session: Session,
    *,
    house_id: UUID,
    tenant_id: UUID,
    enabled_services: list[str],
    quiet_start,
    quiet_end,
    sensitivity: str,
    updated_by: UUID,
) -> None:
    existing = session.get(HouseServiceSetting, house_id)
    if existing is None:
        session.add(
            HouseServiceSetting(
                house_id=house_id,
                tenant_id=tenant_id,
                enabled_services=enabled_services,
                quiet_start=quiet_start,
                quiet_end=quiet_end,
                sensitivity=sensitivity,
                updated_by=updated_by,
            )
        )
    else:
        existing.enabled_services = enabled_services
        existing.quiet_start = quiet_start
        existing.quiet_end = quiet_end
        existing.sensitivity = sensitivity
        existing.updated_by = updated_by


def _upsert_contact(
    session: Session,
    *,
    contact_id: UUID,
    house_id: UUID,
    tenant_id: UUID,
    name: str,
    email: str,
    contact_type: str,
    priority: int,
) -> None:
    existing = session.get(EmergencyContact, contact_id)
    if existing is None:
        session.add(
            EmergencyContact(
                contact_id=contact_id,
                house_id=house_id,
                tenant_id=tenant_id,
                name=name,
                email=email,
                contact_type=contact_type,
                priority=priority,
            )
        )
    else:
        existing.name = name
        existing.email = email
        existing.contact_type = contact_type
        existing.priority = priority


def _upsert_service_client(session: Session, client_id: str, scopes: list[str]) -> None:
    existing = session.get(ServiceClient, client_id)
    if existing is None:
        session.add(
            ServiceClient(
                client_id=client_id,
                secret_hash=_hash(_client_secret(client_id)),
                scopes=scopes,
                is_active=True,
            )
        )
    else:
        # Rotate the secret on every seed run so env changes take effect.
        existing.secret_hash = _hash(_client_secret(client_id))
        existing.scopes = scopes
        existing.is_active = True


def run() -> dict:
    """Seed the C4 schema. Returns a small summary dict."""
    from datetime import time

    _ensure_schema()
    with session_scope() as session:
        # tenants
        _upsert_tenant(session, "acme", UUID(TENANTS["acme"]), "Acme Care", "America/Los_Angeles")
        _upsert_tenant(
            session, "sunrise", UUID(TENANTS["sunrise"]), "Sunrise Living", "America/New_York"
        )

        # users
        for email, (uid, role, tenant_alias, house_aliases) in USERS.items():
            tenant_id = UUID(TENANTS[tenant_alias]) if tenant_alias else None
            house_ids = [UUID(HOUSES[h][0]) for h in house_aliases]
            _upsert_user(
                session,
                user_id=UUID(uid),
                tenant_id=tenant_id,
                email=email,
                role=role,
                house_ids=house_ids,
            )

        ops_id = UUID(USERS["ops@homeai.test"][0])

        # settings: Maple (quiet hours) and Oak (defaults)
        maple_id = UUID(HOUSES["maple"][0])
        oak_id = UUID(HOUSES["oak"][0])
        acme_id = UUID(TENANTS["acme"])
        _upsert_settings(
            session,
            house_id=maple_id,
            tenant_id=acme_id,
            enabled_services=ALL_SERVICES,
            quiet_start=time(22, 0),
            quiet_end=time(6, 0),
            sensitivity="medium",
            updated_by=ops_id,
        )
        _upsert_settings(
            session,
            house_id=oak_id,
            tenant_id=acme_id,
            enabled_services=ALL_SERVICES,
            quiet_start=None,
            quiet_end=None,
            sensitivity="medium",
            updated_by=ops_id,
        )

        # Maple emergency contacts
        contact_data = [
            ("Alice Maple", "alice.maple@example.test", "family", 1),
            ("Bob Caregiver", "bob.care@example.test", "caregiver", 2),
            ("Carol Neighbor", "carol.neighbor@example.test", "neighbor", 3),
        ]
        for cid, (name, cemail, ctype, priority) in zip(MAPLE_CONTACTS, contact_data, strict=True):
            _upsert_contact(
                session,
                contact_id=UUID(cid),
                house_id=maple_id,
                tenant_id=acme_id,
                name=name,
                email=cemail,
                contact_type=ctype,
                priority=priority,
            )

        # service clients
        for client_id in SERVICE_CLIENTS:
            _upsert_service_client(session, client_id, SERVICE_CLIENT_SCOPES.get(client_id, []))

    return {
        "tenants": len(TENANTS),
        "users": len(USERS),
        "settings": 2,
        "contacts": len(MAPLE_CONTACTS),
        "service_clients": len(SERVICE_CLIENTS),
    }


if __name__ == "__main__":  # pragma: no cover
    summary = run()
    print("C4 seed complete:", summary)
