"""JWKS endpoint: GET /.well-known/jwks.json (contracts §4.7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_jwt_issuer
from app.services.jwt_issuer import JwtIssuer

router = APIRouter(tags=["jwks"])


@router.get("/.well-known/jwks.json")
def jwks(issuer: JwtIssuer = Depends(get_jwt_issuer)) -> dict:
    return issuer.jwks()
