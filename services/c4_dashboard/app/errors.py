"""Shared error envelope and FastAPI exception handlers (contracts §1).

Until P0-3 ships `homeai_common.errors`, C4 keeps a local implementation that
emits the same `{"error": {"code", "message", "details"}}` shape.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


def _envelope(code: str, message: str, details: Any | None = None) -> dict:
    body = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"error": body}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content=_envelope(exc.code, exc.message, exc.details)
        )

    @app.exception_handler(HTTPException)
    async def _http_exception(_: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            code = exc.detail["code"]
            message = exc.detail.get("message", exc.status_code)
            details = exc.detail.get("details")
        else:
            code = "unknown"
            message = str(exc.detail) if exc.detail is not None else ""
            details = None
        # Map common FastAPI status codes to contract codes when no explicit code was given.
        if code == "unknown":
            code = {
                status.HTTP_401_UNAUTHORIZED: "unauthorized",
                status.HTTP_403_FORBIDDEN: "forbidden",
                status.HTTP_404_NOT_FOUND: "not_found",
                status.HTTP_409_CONFLICT: "invalid_state",
                status.HTTP_422_UNPROCESSABLE_ENTITY: "validation_error",
                status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
                status.HTTP_503_SERVICE_UNAVAILABLE: "dependency_unavailable",
            }.get(exc.status_code, code)
        return JSONResponse(status_code=exc.status_code, content=_envelope(code, message, details))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(p) for p in err["loc"][1:]) or str(err["loc"][-1]),
                "issue": err["msg"],
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_envelope("validation_error", "request validation failed", details),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("internal_error", "unexpected error"),
        )
