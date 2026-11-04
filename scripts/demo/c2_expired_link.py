#!/usr/bin/env python3
"""Print an alert-view link that has already expired (demo step: expired link -> 401 page).

The token is signed with C2's real key, exactly like the links in alert emails, but dated as if
the alert fired 25 hours ago (links live 24 h). Opening it shows the "link expired" page;
``GET /api/v1/alert-view/<token>`` answers 401 ``token_expired``.

    python scripts/demo/c2_expired_link.py                    # newest alert (needs DATABASE_URL_C2)
    python scripts/demo/c2_expired_link.py --alert-id <uuid> [--contact-id <uuid>]

The key comes from C2's settings, as in the service: ``C2_ALERT_VIEW_KEY`` (base64) if set,
otherwise Secrets Manager ``homeai/alert-view-hmac`` (LocalStack from the host:
``AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test``).
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "homeai_common"))
sys.path.insert(0, str(ROOT / "services" / "c2_alerts"))

from app.gateways.secrets_gateway import AlertViewKeyProvider  # noqa: E402
from app.gateways.types import DependencyUnavailableError  # noqa: E402
from app.services.signed_link import LINK_TTL, SignedLinkService  # noqa: E402
from app.settings import Settings  # noqa: E402

EXPIRED_FOR = timedelta(hours=1)


def links_from_settings(settings: Settings) -> SignedLinkService:
    # demo_mode=False: never fall back to a made-up key, or the server could not verify it.
    keys = AlertViewKeyProvider(
        secret_id=settings.alert_view_key_secret,
        region=settings.aws_region,
        endpoint_url=settings.aws_endpoint,
        override_b64=settings.alert_view_key,
        demo_mode=False,
    )
    return SignedLinkService(keys=keys, public_base_url=settings.public_base_url)


def newest_alert_in(session) -> tuple[str, str | None] | None:
    """(alert_id, contact_id of its first emailed contact) of the newest alert, if any."""
    from app.models.orm import Alert, Notification
    from sqlalchemy import select

    alert = session.scalars(select(Alert).order_by(Alert.triggered_at.desc())).first()
    if alert is None:
        return None
    contact = session.scalars(
        select(Notification.contact_id)
        .where(Notification.alert_id == alert.alert_id, Notification.channel == "email")
        .order_by(Notification.priority)
    ).first()
    return alert.alert_id, contact


def newest_alert(database_url: str) -> tuple[str, str | None] | None:  # pragma: no cover
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            return newest_alert_in(session)
    finally:
        engine.dispose()


def main(
    argv: list[str] | None = None,
    *,
    links: SignedLinkService | None = None,
    lookup: Callable[[str], tuple[str, str | None] | None] = newest_alert,
    now: datetime | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--alert-id", help="default: the newest alert in c2.alerts")
    parser.add_argument("--contact-id", help="default: the alert's first emailed contact")
    args = parser.parse_args(argv)

    alert_id, contact_id = args.alert_id, args.contact_id
    if alert_id is None:
        url = os.environ.get("DATABASE_URL_C2")
        try:
            found = lookup(url) if url else None
        except Exception as exc:  # e.g. .env's container hostname used from the host
            print(f"cannot read c2.alerts ({type(exc).__name__}); pass --alert-id to pick one")
            found = None
        if found is None:
            # Expiry is checked before the alert is looked up, so the page still says "expired".
            print("no alert found (set DATABASE_URL_C2 or --alert-id); using a made-up alert id")
            found = (str(uuid.uuid4()), None)
        alert_id, contact_id = found[0], contact_id or found[1]
    contact_id = contact_id or str(uuid.uuid4())

    links = links or links_from_settings(Settings())
    fired = (now or datetime.now(UTC)) - LINK_TTL - EXPIRED_FOR
    try:
        token = links.issue(alert_id, contact_id, fired)
    except DependencyUnavailableError as exc:
        print(
            f"cannot read the alert-view key ({exc.source}): set C2_ALERT_VIEW_KEY or the AWS env"
        )
        return 1
    print(f"alert {alert_id}, contact {contact_id}: link expired {EXPIRED_FOR} ago")
    print(links.link(token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
