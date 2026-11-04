"""C4 house service settings and emergency contacts (read-only, contracts §4.5)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.gateways.readonly_tables import emergency_contacts as ec
from app.gateways.readonly_tables import house_service_settings as hss
from app.gateways.sql_errors import read_or_unavailable
from app.gateways.types import Contact, HouseSettings

SOURCE = "c4"


class C4SettingsGateway:
    """Implements ``SettingsReader`` over the ``c2_reader`` session."""

    def __init__(self, session: Session):
        self.session = session

    def settings(self, house_id: str) -> HouseSettings:
        stmt = select(
            hss.c.house_id,
            hss.c.tenant_id,
            hss.c.enabled_services,
            hss.c.quiet_start,
            hss.c.quiet_end,
            hss.c.sensitivity,
        ).where(hss.c.house_id == house_id)
        row = read_or_unavailable(self.session, SOURCE, lambda: self.session.execute(stmt).first())
        if row is None:
            return HouseSettings.defaults(house_id)
        return HouseSettings(
            house_id=row.house_id,
            tenant_id=row.tenant_id,
            enabled_services=frozenset(row.enabled_services or ()),
            quiet_start=row.quiet_start,
            quiet_end=row.quiet_end,
            sensitivity=row.sensitivity,
        )

    def contacts(self, house_id: str) -> list[Contact]:
        """Emergency contacts in priority order (1 = first to notify)."""
        stmt = (
            select(ec.c.contact_id, ec.c.name, ec.c.email, ec.c.contact_type, ec.c.priority)
            .where(ec.c.house_id == house_id)
            .order_by(ec.c.priority)
        )
        rows = read_or_unavailable(self.session, SOURCE, lambda: self.session.execute(stmt).all())
        return [
            Contact(
                contact_id=r.contact_id,
                name=r.name,
                email=r.email,
                contact_type=r.contact_type,
                priority=r.priority,
            )
            for r in rows
        ]

    def contact_houses(self) -> list[str]:
        stmt = select(ec.c.house_id).distinct().order_by(ec.c.house_id)
        rows = read_or_unavailable(self.session, SOURCE, lambda: self.session.scalars(stmt).all())
        return [str(h) for h in rows]
