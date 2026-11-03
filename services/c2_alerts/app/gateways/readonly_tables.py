"""Read-only views of other components' tables (only the columns contract §4.5 lets C2 read).

Kept on their own MetaData so Alembic never treats them as C2 tables.
"""

from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    Column,
    DateTime,
    MetaData,
    SmallInteger,
    String,
    Table,
    Text,
    Time,
)
from sqlalchemy.dialects.postgresql import UUID

U = UUID(as_uuid=False)
foreign = MetaData()

house_service_settings = Table(
    "house_service_settings",
    foreign,
    Column("house_id", U, primary_key=True),
    Column("tenant_id", U),
    Column("enabled_services", ARRAY(Text)),
    Column("quiet_start", Time),
    Column("quiet_end", Time),
    Column("sensitivity", String(6)),
    schema="c4",
)

emergency_contacts = Table(
    "emergency_contacts",
    foreign,
    Column("contact_id", U, primary_key=True),
    Column("house_id", U),
    Column("name", String(80)),
    Column("email", String(254)),
    Column("contact_type", String(20)),
    Column("priority", SmallInteger),
    schema="c4",
)

houses = Table(
    "houses",
    foreign,
    Column("house_id", U, primary_key=True),
    Column("tenant_id", U),
    Column("name", String(80)),
    Column("timezone", String(40)),
    Column("deleted_at", DateTime(timezone=True)),
    schema="c1",
)

rooms = Table(
    "rooms",
    foreign,
    Column("room_id", U, primary_key=True),
    Column("house_id", U),
    Column("name", String(60)),
    schema="c1",
)
