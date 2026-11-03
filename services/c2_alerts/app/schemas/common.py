"""Shared field types for C2 request/response models."""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import AfterValidator


def _uuid_str(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("must be a UUID") from exc


# UUID as a lowercase string (contracts §1: IDs are UUID strings everywhere).
UuidStr = Annotated[str, AfterValidator(_uuid_str)]
