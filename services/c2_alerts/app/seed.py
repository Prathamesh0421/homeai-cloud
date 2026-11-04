"""C2 part of the demo seed: the tenant default rules (one per alert type) for the seed tenants.

Alert types come from migration 0002. Run inside the C2 container after the migrations
(``scripts/seed.py`` calls it; idempotent, so it can run on every seed):

    docker compose exec c2-alerts python -m app.seed [--tenant <uuid> ...]
"""

from __future__ import annotations

import argparse
import logging

from homeai_common import db
from sqlalchemy.orm import Session

from app.services.rule_service import RuleService
from app.settings import get_settings

logger = logging.getLogger(__name__)

# The seed tenants and ops user from scripts/seed_ids.py (not in the image; a test keeps the two
# lists equal).
SEED_TENANTS = (
    "11111111-0000-0000-0000-000000000001",  # Acme Care
    "11111111-0000-0000-0000-000000000002",  # Sunrise Living
)
SEED_OPS_USER = "44444444-0000-0000-0000-000000000001"  # ops@homeai.test (cloud_staff)


class _NoHouseLookups:
    """Tenant default rules have no house, so RuleService never asks C1 for one here."""

    def __getattr__(self, name: str):
        raise RuntimeError(f"the C2 seed does not look up houses ({name})")


def seed_rules(session: Session, tenant_ids: tuple[str, ...] = SEED_TENANTS) -> dict[str, int]:
    """Create the missing default rules per tenant; returns how many each tenant got."""
    service = RuleService(session, houses=_NoHouseLookups())
    return {t: service.create_defaults(t, created_by=SEED_OPS_USER) for t in tenant_ids}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed C2's tenant default alert rules.")
    parser.add_argument("--tenant", action="append", help="tenant UUID (default: seed tenants)")
    args = parser.parse_args(argv)
    settings = get_settings()
    db.configure_db(settings.database_url)
    try:
        with db.session_scope() as session:
            created = seed_rules(session, tuple(args.tenant) if args.tenant else SEED_TENANTS)
    finally:
        db.dispose_db()
    for tenant, count in created.items():
        print(f"c2 seed: tenant {tenant}: {count} default rule(s) created")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
