"""Health endpoint: GET /api/v1/health/c4 (contracts §1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.settings import Settings

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("/c4", status_code=status.HTTP_200_OK)
def health(settings: Settings = Depends(lambda: Settings()), db: Session = Depends(get_db)) -> dict:
    body = {"status": "ok", "db": "ok", "mongo": "ok", "version": settings.git_sha}
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        body["db"] = "error"
        body["status"] = "degraded"
    return body
