"""Domain errors raised by repositories (no HTTP here; services map them to ApiError)."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError


class DuplicateRuleError(Exception):
    """An enabled rule already exists for this tenant/house/type/room (``ux_rules_dup``)."""


class DuplicateDetectionError(Exception):
    """An alert already exists for this ``detection_id`` (``alerts_detection_id_key``)."""


def violated_constraint(exc: IntegrityError) -> str | None:
    """Name of the constraint/index behind a psycopg IntegrityError, if known."""
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)
