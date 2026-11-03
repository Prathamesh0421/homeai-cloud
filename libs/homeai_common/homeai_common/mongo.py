"""PyMongo client singleton (contracts §5.2).

IDs are UUID strings (``_id`` included), so ``uuidRepresentation="standard"`` only matters if
a native UUID slips in. ``tz_aware=True`` returns UTC-aware datetimes so they serialise with
``Z``. The short server-selection timeout keeps health checks and requests from hanging for
pymongo's default 30 s when Mongo is down.
"""

from __future__ import annotations

from typing import Any

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.uri_parser import parse_uri

DEFAULT_DB_NAME = "homeai"
SERVER_SELECTION_TIMEOUT_MS = 3000

_clients: dict[str, MongoClient] = {}


def get_mongo_client(url: str, **kwargs: Any) -> MongoClient:
    """One client per URL for the whole process (PyMongo clients are thread-safe pools)."""
    client = _clients.get(url)
    if client is None:
        options: dict[str, Any] = {
            "uuidRepresentation": "standard",
            "tz_aware": True,
            "serverSelectionTimeoutMS": SERVER_SELECTION_TIMEOUT_MS,
        }
        options.update(kwargs)
        client = MongoClient(url, **options)
        _clients[url] = client
    return client


def get_mongo_db(url: str, name: str | None = None) -> Database:
    """Database named in the URL path (``mongodb://user:pw@mongo:27017/homeai``), else ``homeai``."""
    db_name = name or parse_uri(url).get("database") or DEFAULT_DB_NAME
    return get_mongo_client(url)[db_name]


def close_mongo() -> None:
    for client in _clients.values():
        client.close()
    _clients.clear()


def check_mongo(db: Database) -> None:
    """Health check: raises if the server does not answer ``ping``."""
    db.command("ping")
