"""Public signed-link alert view (no login; rate limited per client IP)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from homeai_common.errors import ApiError, ErrorEnvelope
from homeai_common.pagination import Envelope, data_response
from sqlalchemy.orm import Session

from app.api.deps import (
    get_clip_reader,
    get_clock,
    get_detection_reader,
    get_house_reader,
    get_session,
)
from app.gateways.types import ClipUrlReader, DetectionReader, HouseReader
from app.schemas.alert_view import AlertView
from app.services.alert_service import AlertService
from app.services.alert_view import AlertViewService

router = APIRouter(prefix="/api/v1/alert-view", tags=["alert view (public)"])


def rate_limited(request: Request) -> None:
    """60 requests/min per client IP (contracts §1.1 ``rate_limited``), before any token work."""
    ip = request.client.host if request.client else "unknown"
    retry_after = request.app.state.alert_view_limiter.hit(ip)
    if retry_after:
        raise ApiError(
            429,
            "rate_limited",
            "too many requests; try again shortly",
            {"retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )


@router.get(
    "/{token}",
    response_model=Envelope[AlertView],
    responses={
        401: {"model": ErrorEnvelope, "description": "token_expired"},
        404: {"model": ErrorEnvelope, "description": "invalid link or unknown alert"},
        429: {"model": ErrorEnvelope, "description": "rate_limited"},
    },
    summary="Alert summary for an emergency contact's signed 24-hour link",
)
def view_alert(
    token: str,
    request: Request,
    _: None = Depends(rate_limited),
    session: Session = Depends(get_session),
    houses: HouseReader = Depends(get_house_reader),
    detections: DetectionReader | None = Depends(get_detection_reader),
    clips: ClipUrlReader | None = Depends(get_clip_reader),
    clock: Callable[[], datetime] = Depends(get_clock),
):
    service = AlertViewService(
        links=request.app.state.links,
        alerts=AlertService(session, houses, detections),
        clips=clips,
    )
    return data_response(service.view(token, clock()))
