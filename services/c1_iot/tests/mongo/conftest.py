"""MongoDB fixtures: a throwaway collection per test.

Needs ``MONGO_URL_C1``. Locally the tests skip without it; on CI (``CI=true``) a missing or
unreachable Mongo is a failure.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from homeai_common.mongo import close_mongo, get_mongo_db
from pymongo.collection import Collection

MONGO_URL = os.environ.get("MONGO_URL_C1")


def _unavailable(reason: str) -> None:
    if os.environ.get("CI") == "true":
        pytest.fail(f"MongoDB required on CI: {reason}", pytrace=False)
    pytest.skip(reason)


@pytest.fixture(scope="session")
def mongo_db():
    if not MONGO_URL:
        _unavailable("MONGO_URL_C1 not set")
    db = get_mongo_db(MONGO_URL)
    try:
        db.command("ping")
    except Exception as exc:  # pragma: no cover - environment dependent
        _unavailable(f"MongoDB unreachable: {exc}")
    yield db
    close_mongo()


@pytest.fixture
def collection(mongo_db) -> Iterator[Collection]:
    coll = mongo_db[f"media_events_test_{uuid.uuid4().hex[:12]}"]
    yield coll
    coll.drop()
