"""Generate the data dictionary from the live schema (C3-13, docs §4.7, Rev4 §6).

The Postgres side is reflected from ``information_schema.columns`` across all four schemas
(c1..c4), so a migration that adds a column shows up automatically (no hand-kept list to
drift). MongoDB has no ``information_schema``; its C3-owned collection shapes are declared in
``app.dictionary.mongo_schemas`` and merged in. Field descriptions come from
``app.dictionary.descriptions``.

No single non-superuser role can read all four schemas: ``c3_app`` owns schema c3 but has no
USAGE on c1/c2/c4, while ``c3_reader`` has USAGE on c1/c2/c4 but none on c3 (``init.sql`` grants
them that way on purpose, and we do not change it). So the generator reflects each subset on the
role that is granted it: schema c3 on the ``c3_app`` connection, and c1/c2/c4 on the
``c3_reader`` connection. Neither helper is ever called with a schema its connection cannot USE.

Fail-closed (mirrors ``record_query._safe_c1_query``): a schema whose tables are simply absent
(C1 has not shipped) contributes nothing — the documented empty state, not an error. An
existing-but-unreadable schema (``_assert_schemas_readable``) or a read denied by a missing
grant (``42501``) is re-raised loudly, never swallowed, so a grant regression surfaces instead
of silently producing a short dictionary forever.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import ProgrammingError

from app.dictionary.descriptions import describe
from app.dictionary.mongo_schemas import MONGO_COLLECTIONS

logger = logging.getLogger("c3.dictionary")

# The four component schemas and the component that owns each.
SCHEMA_OWNER = {"c1": "c1", "c2": "c2", "c3": "c3", "c4": "c4"}
# Which connection reflects which schemas: c3 on the c3_app connection (owns it), c1/c2/c4 on
# the c3_reader connection (granted USAGE/SELECT in init.sql). No role can USE all four.
OWN_SCHEMAS = ["c3"]
CROSS_SCHEMAS = ["c1", "c2", "c4"]


class SchemaUnreadable(Exception):
    """A schema exists but the connecting role cannot read it — fail loud, don't under-report."""


def _assert_schemas_readable(conn: Connection, schemas: list[str]) -> None:
    """Loud fail-closed guard for the information_schema blind spot, over ``schemas``.

    ``information_schema.columns`` silently omits rows the connecting role may not see, so an
    unreadable schema looks identical to an absent one. That is exactly the drift the dictionary
    must not hide: an existing-but-unreadable schema would quietly shrink the dictionary forever.
    So we check existence against ``pg_catalog.pg_namespace`` (visible to every role, unlike
    ``information_schema.schemata`` which itself hides schemas the role lacks privilege on) and
    then test USAGE: a schema that EXISTS but the role cannot USE raises. A schema that does not
    exist (e.g. c1 pre-ship) is the legitimate absent-as-empty case and is left alone.

    Called only with the schema subset the connection's role is granted; a subset that includes
    a schema the role cannot USE is the regression this guard is meant to catch.
    """
    rows = conn.execute(
        text(
            "SELECT n.nspname, has_schema_privilege(n.nspname, 'USAGE') AS usable "
            "FROM pg_catalog.pg_namespace n WHERE n.nspname = ANY(:schemas)"
        ),
        {"schemas": schemas},
    ).all()
    unreadable = [name for name, usable in rows if not usable]
    if unreadable:
        logger.warning(
            "data-dictionary: schema(s) exist but are not readable by this role",
            extra={"schemas": unreadable},
        )
        raise SchemaUnreadable(
            f"schema(s) exist but are unreadable (check grants): {', '.join(sorted(unreadable))}"
        )


def _pg_entities(conn: Connection, schemas: list[str]) -> list[dict]:
    """Reflect every table in ``schemas`` from information_schema.columns on ``conn``.

    Returns one entity dict per (schema, table). A schema with no tables (e.g. c1 pre-ship)
    contributes nothing. An existing-but-unreadable schema or a missing grant re-raises (loud).
    """
    _assert_schemas_readable(conn, schemas)
    try:
        rows = (
            conn.execute(
                text(
                    "SELECT table_schema, table_name, column_name, data_type, is_nullable, "
                    "ordinal_position "
                    "FROM information_schema.columns "
                    "WHERE table_schema = ANY(:schemas) "
                    "ORDER BY table_schema, table_name, ordinal_position"
                ),
                {"schemas": schemas},
            )
            .mappings()
            .all()
        )
    except ProgrammingError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None) or ""
        if sqlstate == "42501":  # insufficient_privilege: a real grant problem, fail loud
            logger.warning(
                "data-dictionary reflection denied (insufficient_privilege); check reader grants",
                extra={"sqlstate": sqlstate},
            )
        raise

    grouped: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        key = (r["table_schema"], r["table_name"])
        grouped.setdefault(key, []).append(
            {
                "name": r["column_name"],
                "type": r["data_type"],
                "nullable": r["is_nullable"] == "YES",
                "internal": False,
                "description": describe(r["table_name"], r["column_name"]),
            }
        )

    entities: list[dict] = []
    for (schema, table), fields in grouped.items():
        entities.append(
            {
                "name": table,
                "store": "postgres",
                "schema_name": schema,
                "owner_component": SCHEMA_OWNER[schema],
                "fields": fields,
            }
        )
    return entities


def _mongo_entities() -> list[dict]:
    """Build the Mongo entities from the declared collection shapes + descriptions."""
    entities: list[dict] = []
    for col in MONGO_COLLECTIONS:
        fields = [
            {
                "name": f["name"],
                "type": f["type"],
                "nullable": None,  # Mongo is schemaless; nullability is not reflected
                "internal": bool(f.get("internal", False)),
                "description": describe(col["name"], f["name"]),
            }
            for f in col["fields"]
        ]
        entities.append(
            {
                "name": col["name"],
                "store": "mongo",
                "schema_name": None,
                "owner_component": col["owner_component"],
                "fields": fields,
            }
        )
    return entities


def generate(
    app_conn: Connection,
    reader_conn: Connection,
    version: str,
    now: datetime | None = None,
) -> dict:
    """Build the full dictionary document for ``version`` from the live schema + Mongo shapes.

    Reflects schema c3 on ``app_conn`` (the c3_app connection, which owns c3) and c1/c2/c4 on
    ``reader_conn`` (the c3_reader connection, which is granted USAGE/SELECT on them). No single
    role can USE all four schemas, so each subset is read on the role granted it;
    ``_assert_schemas_readable`` still fails loud if a subset hits a schema its role cannot use.

    ``generated_at`` is stored as an ISO-8601 ``Z`` string: the document lands in a JSONB column
    and a bare ``datetime`` is not JSON-serialisable.
    """
    now = (now or datetime.now(UTC)).astimezone(UTC)
    entities = (
        _pg_entities(app_conn, OWN_SCHEMAS)  # c3 via c3_app (owns it)
        + _pg_entities(reader_conn, CROSS_SCHEMAS)  # c1/c2/c4 via c3_reader (granted)
        + _mongo_entities()
    )
    # Stable order: by owner component, then store, then entity name.
    entities.sort(key=lambda e: (e["owner_component"], e["store"], e["name"]))
    generated_at = now.isoformat().replace("+00:00", "Z")
    return {"version": version, "generated_at": generated_at, "entities": entities}


def group_by_component(document: dict) -> dict:
    """Regroup a document's entities under their owner component for GET /data-dictionary."""
    groups: dict[str, list[dict]] = {}
    for ent in document.get("entities", []):
        groups.setdefault(ent["owner_component"], []).append(ent)
    return {
        "version": document.get("version"),
        "generated_at": document.get("generated_at"),
        "components": [{"component": comp, "entities": groups[comp]} for comp in sorted(groups)],
    }


def to_csv(document: dict) -> str:
    """Flatten a document to CSV: one row per field across all entities."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "component",
            "store",
            "schema",
            "entity",
            "field",
            "type",
            "nullable",
            "internal",
            "description",
        ]
    )
    for ent in document.get("entities", []):
        for f in ent["fields"]:
            writer.writerow(
                [
                    ent["owner_component"],
                    ent["store"],
                    ent.get("schema_name") or "",
                    ent["name"],
                    f["name"],
                    f["type"],
                    "" if f.get("nullable") is None else str(f["nullable"]).lower(),
                    str(bool(f.get("internal", False))).lower(),
                    f.get("description") or "",
                ]
            )
    return buf.getvalue()
