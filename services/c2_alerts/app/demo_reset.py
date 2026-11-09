"""Clear C2's demo activity between rehearsals: alerts, their status history and notifications.

Keeps everything the demo is set up with: alert types, rules, and the SNS topics and confirmed
email subscriptions (those live in SNS, not here). DEMO_MODE only; ``--yes`` to delete.

    docker compose exec c2-alerts python -m app.demo_reset --yes [--house <uuid>]

Detections stay in C3's ``ai_detections``: re-sending one after a reset raises a new alert.
"""

from __future__ import annotations

import argparse

from homeai_common import db
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.orm import Alert, AlertStatusHistory, Notification
from app.settings import get_settings


def reset_alerts(session: Session, house_id: str | None = None) -> dict[str, int]:
    """Delete alerts (all, or one house's) with their history and notifications; counts deleted."""
    in_scope = [Alert.house_id == house_id] if house_id else []
    alerts = select(Alert.alert_id).where(*in_scope)
    counts = {}
    # Children first: both reference c2.alerts.
    for name, model in (("notifications", Notification), ("history", AlertStatusHistory)):
        counts[name] = session.execute(delete(model).where(model.alert_id.in_(alerts))).rowcount
    counts["alerts"] = session.execute(delete(Alert).where(*in_scope)).rowcount
    return counts


def remaining(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Alert)) or 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clear C2's demo alerts (keeps rules).")
    parser.add_argument("--house", help="only this house's alerts (UUID)")
    parser.add_argument("--yes", action="store_true", help="delete (otherwise only counts)")
    args = parser.parse_args(argv)
    settings = get_settings()
    if not settings.demo_mode:
        print("refusing: DEMO_MODE is off (this deletes alerts)")
        return 2
    db.configure_db(settings.database_url)
    try:
        with db.session_scope() as session:
            if not args.yes:
                print(f"c2 demo reset: {remaining(session)} alert(s); run again with --yes")
                return 0
            counts = reset_alerts(session, args.house)
    finally:
        db.dispose_db()
    print(
        "c2 demo reset: deleted {alerts} alert(s), {history} history row(s), "
        "{notifications} notification(s); rules kept".format(**counts)
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
