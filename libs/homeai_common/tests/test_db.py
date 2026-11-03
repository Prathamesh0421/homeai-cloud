"""Engine/session helpers, exercised against in-memory SQLite (no Postgres needed)."""

from __future__ import annotations

import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from homeai_common import db
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

SQLITE = "sqlite+pysqlite:///:memory:"
SHARED = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}


@pytest.fixture(autouse=True)
def configured():
    db.configure_db(SQLITE, reader_url=SQLITE, **SHARED)
    with db.get_engine().begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))
    yield
    db.dispose_db()


def _count() -> int:
    with db.get_engine().connect() as conn:
        return conn.execute(text("SELECT count(*) FROM t")).scalar_one()


def test_session_scope_commits():
    with db.session_scope() as s:
        s.execute(text("INSERT INTO t (v) VALUES ('a')"))
    assert _count() == 1


def test_session_scope_rolls_back_on_error():
    with pytest.raises(RuntimeError), db.session_scope() as s:
        s.execute(text("INSERT INTO t (v) VALUES ('a')"))
        raise RuntimeError("fail")
    assert _count() == 0


def test_dependencies_yield_sessions():
    app = FastAPI()

    @app.get("/both")
    def both(rw: Session = Depends(db.get_session), ro: Session = Depends(db.get_reader_session)):
        return {
            "rw": rw.execute(text("SELECT 1")).scalar(),
            "ro": ro.execute(text("SELECT 2")).scalar(),
        }

    assert TestClient(app).get("/both").json() == {"rw": 1, "ro": 2}


def test_check_database_ok():
    db.check_database()
    db.check_database(db.READER)


def test_unconfigured_reader_raises():
    db.configure_db(SQLITE, **SHARED)
    with pytest.raises(RuntimeError, match="reader"):
        db.get_engine(db.READER)
    with pytest.raises(RuntimeError), db.session_scope(db.READER):
        pass


def test_postgres_engine_gets_connect_timeout(monkeypatch):
    captured = {}
    monkeypatch.setattr(db, "create_engine", lambda url, **kw: captured.update(kw) or "engine")
    db.make_engine("postgresql+psycopg://u:p@localhost:1/x")
    assert captured["connect_args"] == {"connect_timeout": db.CONNECT_TIMEOUT_SECONDS}
    assert captured["pool_pre_ping"] is True
    captured.clear()
    db.make_engine(SQLITE)
    assert "connect_args" not in captured


def test_postgres_check_fails_fast_when_unreachable():
    db.configure_db("postgresql+psycopg://u:p@127.0.0.1:1/x")
    started = time.monotonic()
    with pytest.raises(OperationalError):
        db.check_database()
    assert time.monotonic() - started < db.CONNECT_TIMEOUT_SECONDS + 2
