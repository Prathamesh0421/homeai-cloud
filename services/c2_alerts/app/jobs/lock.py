"""Postgres advisory locks so each job runs in one place at a time (several API processes).

The lock is a transaction-level advisory lock on its own connection, held until the job is
done. It cannot be the job's session: the job commits row by row, and each commit would release
a transaction lock. A transaction lock (rather than a session lock) is also released if the
job crashes, so it can never stay behind on a pooled connection.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import Engine

# One fixed 64-bit key per job ("C2" + job number).
RETRY_LOCK = 0x4332_0000_0001
SYNC_LOCK = 0x4332_0000_0002


@contextmanager
def advisory_lock(engine: Engine, key: int) -> Iterator[bool]:
    """Yield True if this caller holds the lock for the block, False if someone else does."""
    with engine.connect() as conn, conn.begin():
        yield bool(conn.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key}).scalar())
