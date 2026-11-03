"""Public alert view behind a signed link (C2 plan §3, §4.4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from homeai_common.errors import ApiError

from app.repositories.scope import Scope
from app.schemas.alert_view import AlertView, AlertViewLabel
from app.services.alert_service import AlertService
from app.services.signed_link import ExpiredLink, InvalidLink, SignedLinkService


def _not_found() -> ApiError:
    # Same answer for malformed, tampered and unknown links: reveal nothing.
    return ApiError(404, "not_found", "this alert link is not valid")


@dataclass
class AlertViewService:
    links: SignedLinkService
    alerts: AlertService

    def view(self, token: str, now: datetime) -> AlertView:
        try:
            claims = self.links.verify(token, now)
        except InvalidLink as exc:
            raise _not_found() from exc
        except ExpiredLink as exc:
            raise ApiError(401, "token_expired", "this alert link has expired") from exc

        alert = self.alerts.alerts.get(claims.alert_id, Scope.everything())
        if alert is None:
            raise _not_found()
        houses, rooms = self.alerts.names([alert])
        house = houses.get(alert.house_id)
        room = rooms.get(alert.room_id) if alert.room_id else None
        evidence = self.alerts.evidence(alert)
        return AlertView(
            alert_type_name=alert.alert_type.name,
            severity=alert.severity,
            status=alert.status,
            house_name=house.name if house else None,
            room_name=room.name if room else None,
            triggered_at=alert.triggered_at,
            labels=[
                AlertViewLabel(label=x.label, confidence=x.confidence) for x in evidence.labels
            ],
            # STANDIN(C1-07): presigned clip URL from C1 GET /clips/{media_id}/playback-url (C2-11).
            clip_url=None,
            expires_at=claims.expires_at,
        )
