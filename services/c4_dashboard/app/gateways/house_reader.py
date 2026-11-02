"""Read-only access to `c1.houses` for house names in `/auth/me`.

Until C1 exists, this returns null names. The reader uses the `c4_reader`
role per docs/02_CONTRACTS.md §5.1.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

HouseRow = tuple[UUID, str | None]


def fetch_house_names(engine: Engine, house_ids: list[UUID]) -> dict[UUID, str | None]:
    if not house_ids:
        return {}
    # Use a raw query against c1.houses via the c4_reader connection. The table
    # may not exist yet in early dev; swallow the error and return nulls.
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT house_id, name FROM c1.houses "
                    "WHERE house_id = ANY(:ids) AND deleted_at IS NULL"
                ),
                {"ids": list(house_ids)},
            ).all()
        return {row[0]: row[1] for row in rows}
    except Exception:
        return dict.fromkeys(house_ids)
