"""Record browsing across components (C3-10, docs §3.2, §4.6).

Reads seven entities from their owning stores through the read-only role (SQL) or C3's own
Mongo. Every query is tenant/house-scoped (RecordScope) and field filters are restricted to a
per-entity whitelist. Secrets are never exposed (C4 tables are not browsable here).

# C1 dependency: houses, rooms, camera_feeds
# ------------------------------------------
# - These tables live in schema c1, owned by Ekant (C1 IoT Device Manager).
# - C1 migrations have not shipped yet, so these tables do not exist.
# - Until they do, queries against c1.* return empty results, not errors.
# - When C1 migrations land on main:
#   1. Remove the table-existence guard in _safe_c1_query().
#   2. The c3_reader role already has SELECT on c1.* (see init.sql).
#   3. No C3 migration or schema change is needed.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from homeai_common.errors import ApiError
from pymongo.database import Database
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import ProgrammingError

from app.services.record_scope import RecordScope

# Entities and the field filters allowed on each (docs §4.6: a per-entity whitelist).
ENTITIES = {
    "houses": {"store": "c1", "filters": {"name"}},
    "rooms": {"store": "c1", "filters": {"room_type"}},
    "feeds": {"store": "c1", "filters": {"media_kind", "status", "room_id"}},
    "clips": {"store": "mongo", "collection": "media_events", "filters": {"status", "feed_id"}},
    "detections": {
        "store": "mongo",
        "collection": "ai_detections",
        "filters": {"top_label", "room_id"},
    },
    "alerts": {"store": "c2", "filters": {"status", "severity"}},
    "activity_patterns": {
        "store": "mongo",
        "collection": "activity_patterns",
        "filters": {"room_id"},
    },
}

# Timestamp column/field used for the from/to window and newest-first ordering, per entity.
TIME_FIELD = {
    "houses": "created_at",
    "rooms": "created_at",
    "feeds": "created_at",
    "clips": "uploaded_at",
    "detections": "detected_at",
    "alerts": "triggered_at",
    "activity_patterns": "date",
}


def _safe_c1_query(conn: Connection, sql: str, params: dict) -> list[dict]:
    """Run a c1.* query; return [] if the relation does not exist yet (C1 not shipped).

    See the C1 dependency note at the top of this module. Remove this guard once C1 migrations
    land — c3_reader already has SELECT on c1.*.
    """
    try:
        rows = conn.execute(text(sql), params).mappings().all()
        return [dict(r) for r in rows]
    except ProgrammingError as exc:
        # Until C1 ships, a c1.* read fails with undefined_table (42P01); and because the c1
        # tables/grants don't exist yet, the reader role can also see insufficient_privilege
        # (42501). Treat both as "C1 not available yet" -> empty, not an error. Once C1's
        # migration lands (tables + the existing c3_reader grants apply), neither fires.
        sqlstate = getattr(exc.orig, "sqlstate", None) or ""
        if sqlstate in ("42P01", "42501"):
            return []
        raise


class RecordQuery:
    def __init__(self, reader_conn: Connection | None, mongo: Database | None):
        self.conn = reader_conn
        self.mongo = mongo

    # -- dispatch -----------------------------------------------------------
    def list(
        self,
        entity: str,
        scope: RecordScope,
        *,
        house_id: str | None,
        from_: datetime | None,
        to: datetime | None,
        filters: dict[str, str],
        offset: int,
        limit: int,
        principal_is_iot: bool = False,
    ) -> tuple[list[dict], int]:
        spec = self._spec(entity)
        if entity == "alerts" and principal_is_iot:
            raise ApiError(403, "forbidden", "iot staff may not read alerts")
        self._validate_filters(entity, filters, spec)

        if spec["store"] == "mongo":
            return self._mongo_list(
                entity, spec, scope, house_id, from_, to, filters, offset, limit
            )
        return self._sql_list(entity, spec, scope, house_id, from_, to, filters, offset, limit)

    def get(self, entity: str, record_id: str, scope: RecordScope) -> dict | None:
        spec = self._spec(entity)
        if spec["store"] == "mongo":
            doc = self.mongo[spec["collection"]].find_one({"_id": record_id})
            return doc if doc and self._in_scope(doc, scope) else None
        # SQL single-record fetch by primary key.
        rows = self._sql_get(entity, spec, record_id, scope)
        return rows[0] if rows else None

    # -- helpers ------------------------------------------------------------
    def _spec(self, entity: str) -> dict:
        spec = ENTITIES.get(entity)
        if spec is None:
            raise ApiError(404, "unknown_entity", f"unknown entity: {entity}")
        return spec

    def _validate_filters(self, entity: str, filters: dict, spec: dict) -> None:
        allowed: Iterable[str] = spec["filters"]
        bad = [k for k in filters if k not in allowed]
        if bad:
            raise ApiError(
                422,
                "validation_error",
                "unsupported field filter(s)",
                details=[{"field": k, "issue": "not filterable on this entity"} for k in bad],
            )

    def _in_scope(self, doc: dict, scope: RecordScope) -> bool:
        if scope.tenant_id is not None and doc.get("tenant_id") != scope.tenant_id:
            return False
        return not (scope.house_ids is not None and doc.get("house_id") not in set(scope.house_ids))

    # -- Mongo --------------------------------------------------------------
    def _mongo_list(self, entity, spec, scope, house_id, from_, to, filters, offset, limit):
        col = self.mongo[spec["collection"]]
        q: dict[str, Any] = scope.mongo_filter()
        if house_id:
            # An explicit house_id must stay within scope: an owner asking for a house they do
            # not own gets nothing, not someone else's data.
            if scope.house_ids is not None and house_id not in set(scope.house_ids):
                return [], 0
            q["house_id"] = house_id
        for k, v in filters.items():
            q[k] = v
        tf = TIME_FIELD[entity]
        if from_ or to:
            window: dict[str, Any] = {}
            if from_:
                window["$gte"] = from_
            if to:
                window["$lt"] = to
            q[tf] = window
        total = col.count_documents(q)
        cursor = col.find(q).sort(tf, -1).skip(offset).limit(limit)
        return [self._clean(dict(d)) for d in cursor], total

    @staticmethod
    def _clean(doc: dict) -> dict:
        # Expose the Mongo _id as a plain string id field; never leak secrets (none here).
        if "_id" in doc:
            doc["id"] = str(doc.pop("_id"))
        return doc

    # -- SQL ----------------------------------------------------------------
    def _sql_list(self, entity, spec, scope, house_id, from_, to, filters, offset, limit):
        if self.conn is None:
            raise ApiError(503, "dependency_unavailable", "reader database not configured")
        where, params = self._sql_where(entity, scope, house_id, from_, to, filters)
        tf = TIME_FIELD[entity]
        table = self._table(entity)
        if spec["store"] == "c1":
            count_rows = _safe_c1_query(
                self.conn, f"SELECT count(*) AS n FROM {table} {where}", params
            )
            if not count_rows:  # table absent -> empty result
                return [], 0
            total = count_rows[0]["n"]
            params2 = {**params, "lim": limit, "off": offset}
            rows = _safe_c1_query(
                self.conn,
                f"SELECT * FROM {table} {where} ORDER BY {tf} DESC LIMIT :lim OFFSET :off",
                params2,
            )
            return rows, total
        # c2.alerts (table exists).
        total = self.conn.execute(
            text(f"SELECT count(*) AS n FROM {table} {where}"), params
        ).scalar_one()
        params2 = {**params, "lim": limit, "off": offset}
        rows = (
            self.conn.execute(
                text(f"SELECT * FROM {table} {where} ORDER BY {tf} DESC LIMIT :lim OFFSET :off"),
                params2,
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows], total

    def _sql_get(self, entity, spec, record_id, scope):
        if self.conn is None:
            raise ApiError(503, "dependency_unavailable", "reader database not configured")
        table = self._table(entity)
        pk = self._pk(entity)
        where, params = self._sql_where(entity, scope, None, None, None, {})
        clause = f"{where} AND {pk} = :rid" if where else f"WHERE {pk} = :rid"
        params = {**params, "rid": record_id}
        sql = f"SELECT * FROM {table} {clause}"
        if spec["store"] == "c1":
            return _safe_c1_query(self.conn, sql, params)
        rows = self.conn.execute(text(sql), params).mappings().all()
        return [dict(r) for r in rows]

    def _sql_where(self, entity, scope, house_id, from_, to, filters):
        clauses: list[str] = []
        params: dict[str, Any] = {}
        has_tenant = entity != "rooms"  # c1.rooms has no tenant_id column
        has_house = True
        if scope.tenant_id is not None and has_tenant:
            clauses.append("tenant_id = :tenant_id")
            params["tenant_id"] = scope.tenant_id
        if scope.house_ids is not None and has_house:
            if scope.house_ids:
                names = []
                for i, h in enumerate(scope.house_ids):
                    key = f"h{i}"
                    params[key] = h
                    names.append(f":{key}")
                clauses.append(f"house_id IN ({', '.join(names)})")
            else:
                clauses.append("1 = 0")  # owner with no houses sees nothing
        if house_id:
            clauses.append("house_id = :house_id")
            params["house_id"] = house_id
        for k, v in filters.items():
            params[k] = v
            clauses.append(f"{k} = :{k}")
        tf = TIME_FIELD[entity]
        if from_:
            clauses.append(f"{tf} >= :from_")
            params["from_"] = from_
        if to:
            clauses.append(f"{tf} < :to_")
            params["to_"] = to
        # c1 live-set filters.
        if entity == "houses":
            clauses.append("deleted_at IS NULL")
        if entity == "feeds":
            clauses.append("archived_at IS NULL")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    @staticmethod
    def _table(entity: str) -> str:
        return {
            "houses": "c1.houses",
            "rooms": "c1.rooms",
            "feeds": "c1.camera_feeds",
            "alerts": "c2.alerts",
        }[entity]

    @staticmethod
    def _pk(entity: str) -> str:
        return {
            "houses": "house_id",
            "rooms": "room_id",
            "feeds": "feed_id",
            "alerts": "alert_id",
        }[entity]
