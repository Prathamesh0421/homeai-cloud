"""Alembic environment for C4. Uses the app's engine and metadata.

With several c4-dashboard copies (``RUN_MIGRATIONS=1`` on each), migrations must not
race. Before ``upgrade``, this process takes a Postgres session-level advisory lock
on a dedicated C4 key and releases it after. Other copies block on the same lock
until the winner finishes.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from app.db.session import BASE_METADATA
from sqlalchemy import engine_from_config, pool, text

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    return os.environ.get("DATABASE_URL_C4") or config.get_main_option("sqlalchemy.url")


# ConfigParser treats % as interpolation; URL-encoded passwords use %2F etc.
config.set_main_option("sqlalchemy.url", _database_url().replace("%", "%%"))

target_metadata = BASE_METADATA

# Session-level advisory lock for Alembic (S-3). "C4" + migration slot; distinct from
# C1 ConnectivityMonitor (0x4331…) and C2 job locks (0x4332…).
MIGRATION_LOCK_KEY = 0x4334_0000_0001


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="c4",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # Session lock (not xact): migrations commit many times; an xact lock would
        # drop mid-run. Blocking lock so a second copy waits instead of racing.
        connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_KEY})
        connection.commit()
        try:
            context.configure(
                connection=connection, target_metadata=target_metadata, version_table_schema="c4"
            )
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_KEY})
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
