"""Service-token endpoint: POST /api/v1/auth/service-token (contracts §4.7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_jwt_issuer
from app.schemas.auth import ServiceTokenEnvelope, ServiceTokenRequest
from app.services import auth_service
from app.services.jwt_issuer import JwtIssuer

router = APIRouter(prefix="/api/v1/auth", tags=["service-tokens"])


@router.post("/service-token", response_model=ServiceTokenEnvelope, status_code=status.HTTP_200_OK)
def service_token(
    body: ServiceTokenRequest,
    db: Session = Depends(get_db),
    issuer: JwtIssuer = Depends(get_jwt_issuer),
) -> dict:
    result = auth_service.issue_service_token(
        db,
        issuer=issuer,
        client_id=body.client_id,
        client_secret=body.client_secret,
        requested_scopes=body.scope,
    )
    return {"data": result}
