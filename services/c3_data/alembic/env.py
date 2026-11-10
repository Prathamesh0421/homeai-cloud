"""Alembic environment for C3 (schema ``c3``, version table ``c3.alembic_version``)."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from app.models import SCHEMA, Base
from app.settings import Settings
from sqlalchemy import Connection, engine_from_config, pool, text

config = context.config

# Tests pass an open connection via config.attributes["connection"]; then the URL and the
# logging config are left alone.
_given_connection: Connection | None = config.attributes.get("connection")

if config.config_file_name is not None and _given_connection is None:
    fileConfig(config.config_file_name)

# DATABASE_URL_C3 / C3_DATABASE_URL win over alembic.ini.
_url = Settings().database_url or config.get_main_option("sqlalchemy.url")
if _given_connection is None:
    # ConfigParser treats % as interpolation; URL-encoded passwords use %2F etc.
    config.set_main_option("sqlalchemy.url", _url.replace("%", "%%"))

target_metadata = Base.metadata


def _include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    # Only compare our own schema; c1/c2/c4 tables in the same database are not ours.
    if type_ == "schema":
        return name == SCHEMA
    return True


def _ensure_schema(connection: Connection) -> None:
    # Alembic writes c3.alembic_version before the first revision runs, so the schema must
    # exist first. infra/db/init.sql normally creates it; this covers fresh databases. Check
    # before creating so c3_app does not need CREATE on the database when it already exists.
    # The SELECT autobegins a transaction; if we started it we must end it, or Alembic would
    # run the migrations inside it and they would be rolled back when the connection closes.
    started_here = not connection.in_transaction()
    exists = connection.execute(
        text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"), {"s": SCHEMA}
    ).first()
    if not exists:
        connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
    if started_here:
        connection.commit()


def run_migrations_offline() -> None:
    context.configure(
        url=_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=_include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    _ensure_schema(connection)
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=_include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if _given_connection is not None:
        _run(_given_connection)
        return
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _run(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
