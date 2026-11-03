"""Mongo client singleton and options. PyMongo connects lazily, so no server is needed."""

from __future__ import annotations

import pytest
from homeai_common import mongo


@pytest.fixture(autouse=True)
def _reset():
    yield
    mongo.close_mongo()


def test_client_is_cached_per_url():
    a = mongo.get_mongo_client("mongodb://u:p@localhost:27017/homeai")
    b = mongo.get_mongo_client("mongodb://u:p@localhost:27017/homeai")
    c = mongo.get_mongo_client("mongodb://other:p@localhost:27017/homeai")
    assert a is b
    assert a is not c


def test_client_options():
    opts = mongo.get_mongo_client("mongodb://localhost:27017/homeai").options
    assert opts.server_selection_timeout == mongo.SERVER_SELECTION_TIMEOUT_MS / 1000
    assert opts.codec_options.tz_aware is True
    assert opts.codec_options.uuid_representation == 4  # UuidRepresentation.STANDARD


def test_db_name_from_url_or_default_or_explicit():
    assert mongo.get_mongo_db("mongodb://localhost:27017/homeai_test").name == "homeai_test"
    assert mongo.get_mongo_db("mongodb://localhost:27017").name == "homeai"
    assert mongo.get_mongo_db("mongodb://localhost:27017/homeai", name="x").name == "x"


def test_close_clears_cache():
    a = mongo.get_mongo_client("mongodb://localhost:27017/homeai")
    mongo.close_mongo()
    assert mongo.get_mongo_client("mongodb://localhost:27017/homeai") is not a


def test_check_mongo_pings():
    calls = []

    class FakeDb:
        def command(self, name):
            calls.append(name)

    mongo.check_mongo(FakeDb())
    assert calls == ["ping"]
