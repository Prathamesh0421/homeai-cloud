"""Reader grants on c4 tables (contract 02 §5.1).

- c2_reader: house_service_settings and emergency_contacts only (contract §4.5).
- c3_reader: everything except password_hash / secret_hash: the users_public view instead of
  users, and service_clients without secret_hash.

infra/db/init.sql grants USAGE on the schema; the owning migration grants the tables. Databases
bootstrapped with an earlier init.sql had SELECT on every c4 table (and a default privilege for
future ones), so upgrade first revokes those. Roles that do not exist (a database without
init.sql) are skipped.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

GRANTS = {
    "c2_reader": [
        "GRANT SELECT ON c4.house_service_settings, c4.emergency_contacts TO c2_reader",
    ],
    "c3_reader": [
        "GRANT SELECT ON c4.tenants, c4.users_public, c4.revoked_tokens, "
        "c4.house_service_settings, c4.emergency_contacts TO c3_reader",
        "GRANT SELECT (client_id, scopes, is_active) ON c4.service_clients TO c3_reader",
    ],
}


def _role_exists(role: str) -> bool:
    row = op.get_bind().execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
    return row.first() is not None


def upgrade() -> None:
    owner_exists = _role_exists("c4_app")
    for role, grants in GRANTS.items():
        if not _role_exists(role):
            continue
        # Also revokes column privileges.
        op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA c4 FROM {role}")
        if owner_exists:
            op.execute(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE c4_app IN SCHEMA c4 REVOKE ALL ON TABLES FROM {role}"
            )
        for grant in grants:
            op.execute(grant)


def downgrade() -> None:
    for role in GRANTS:
        if _role_exists(role):
            op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA c4 FROM {role}")
