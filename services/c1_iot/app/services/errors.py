"""Contract error helpers (02 §1.1) so services raise the documented codes in one way."""

from __future__ import annotations

from homeai_common.errors import ApiError


def invalid(field: str, issue: str) -> ApiError:
    """422 ``validation_error`` naming one field, same shape as FastAPI's validation errors."""
    return ApiError(
        422, "validation_error", "request validation failed", [{"field": field, "issue": issue}]
    )


def not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"{what} not found")


def conflict(code: str, message: str) -> ApiError:
    return ApiError(409, code, message)
