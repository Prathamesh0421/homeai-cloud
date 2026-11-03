"""Shared error envelope and FastAPI exception handlers (contracts §1, §1.1).

Every error response has the shape::

    {"error": {"code": "snake_case", "message": "human text", "details": {...} | [...]}}

Raise `ApiError` from services and routers. `homeai_common.auth` raises FastAPI
`HTTPException(detail={"code", "message"})`; the HTTP handler unwraps that dict so
auth failures use the same envelope.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import REQUEST_ID_HEADER, request_id_from_scope

logger = logging.getLogger("homeai_common.errors")

# Fallback codes when an HTTPException carries no explicit code. 409 stays neutral on
# purpose: each component raises its own documented 409 code via ApiError.
DEFAULT_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    503: "dependency_unavailable",
}


class ApiError(Exception):
    """An error that maps directly to the contract envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers
        super().__init__(message)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorEnvelope(BaseModel):
    """Use in `responses={404: {"model": ErrorEnvelope}}` so OpenAPI shows the shape."""

    error: ErrorBody


def error_envelope(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"error": body}


def _json(
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_envelope(code, message, details),
        headers=headers,
    )


def _validation_details(exc: RequestValidationError) -> list[dict[str, str]]:
    # Only field + issue: pydantic's "input" would echo request values (e.g. passwords).
    details = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ())]
        if len(loc) > 1 and loc[0] in {"body", "query", "path", "header", "cookie"}:
            loc = loc[1:]
        details.append({"field": ".".join(loc), "issue": str(err.get("msg", "invalid"))})
    return details


async def _handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
    return _json(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        code = str(detail["code"])
        message = str(detail.get("message", ""))
        details = detail.get("details")
    else:
        code = DEFAULT_CODES.get(exc.status_code, "http_error")
        message = str(detail) if detail is not None else ""
        details = None
    return _json(exc.status_code, code, message, details, getattr(exc, "headers", None))


async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
    return _json(
        422,
        "validation_error",
        "request validation failed",
        _validation_details(exc),
    )


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    # Starlette runs this handler outside user middleware, so the request id header is
    # added here from the value RequestIdMiddleware stored in the ASGI scope.
    logger.exception("unhandled exception", exc_info=exc)
    request_id = request_id_from_scope(request.scope)
    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
    return _json(500, "internal_error", "unexpected error", None, headers)


def install_error_handlers(app: FastAPI) -> None:
    """Register envelope handlers for ApiError, HTTP errors, validation and crashes."""
    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(Exception, _handle_unexpected)
