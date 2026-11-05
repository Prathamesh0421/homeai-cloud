"""Media-event operations: requeue a failed clip (C3-09, docs §3.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from homeai_common.auth import require_roles
from homeai_common.errors import ApiError
from homeai_common.pagination import Envelope, data_response
from pymongo.database import Database

from app.api.deps import get_mongo
from app.repositories.media_event_repo import COLLECTION as EV_COLLECTION
from app.repositories.media_event_repo import MediaEventRepo
from app.schemas.inference import RequeueResult

router = APIRouter(prefix="/api/v1/media-events", tags=["media-events"])

cloud = require_roles("cloud_staff")


@router.post(
    "/{media_id}/requeue", response_model=Envelope[RequeueResult], dependencies=[Depends(cloud)]
)
def requeue(media_id: str, mdb: Database = Depends(get_mongo)) -> dict:
    """Reset a failed clip to queued. 404 if unknown; 409 not_failed if not currently failed."""
    repo = MediaEventRepo(mdb[EV_COLLECTION])
    ev = repo.get(media_id)
    if ev is None:
        raise ApiError(404, "not_found", "media event not found")
    if ev.get("status") != "failed":
        raise ApiError(409, "not_failed", "only failed clips can be requeued")
    repo.requeue(media_id)
    return data_response(RequeueResult(media_id=media_id, status="queued"))
