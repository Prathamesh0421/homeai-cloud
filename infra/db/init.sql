-- HomeAI Cloud — PostgreSQL bootstrap (local dev / EC2 one-time)
-- Owner: Renuka (P0-5). Source of truth: docs/02_CONTRACTS.md section 5.1.
--
-- Creates one schema per component, an owner (read/write) role and reader
-- roles, and the cross-schema grants from the contracts. Each service connects
-- as cX_app; read-only connections use cX_reader.
--
-- This script runs IN THE CURRENT DATABASE and does not switch connections, so
-- it is portable across every way it is invoked:
--   * Docker entrypoint  — postgres:16 runs /docker-entrypoint-initdb.d/*.sql
--                           already connected to POSTGRES_DB (homeai).
--   * CI                 — psql -d homeai_migrate|homeai_test -f init.sql
--                           (CI creates these databases and runs this per-db).
--   * EC2 / RDS          — psql -d homeai -f init.sql against the provisioned DB.
-- Creating the database itself is the responsibility of the caller (POSTGRES_DB,
-- RDS provisioning, or the CI "CREATE DATABASE" step) — not this file.
--
-- Idempotency: every object is guarded, so the script is safe to re-run.

-- ---------------------------------------------------------------------------
-- Extensions used by component schemas (c4 stores emails as citext).
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS citext;

-- ---------------------------------------------------------------------------
-- Schemas (one per component)
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS c1;
CREATE SCHEMA IF NOT EXISTS c2;
CREATE SCHEMA IF NOT EXISTS c3;
CREATE SCHEMA IF NOT EXISTS c4;

-- ---------------------------------------------------------------------------
-- Roles. LOGIN roles with the dev password. On AWS the password comes from
-- Secrets Manager and this file is edited/parameterised before running.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  -- Owner (read/write) roles
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'c1_app') THEN
    CREATE ROLE c1_app LOGIN PASSWORD 'devpass';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'c2_app') THEN
    CREATE ROLE c2_app LOGIN PASSWORD 'devpass';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'c3_app') THEN
    CREATE ROLE c3_app LOGIN PASSWORD 'devpass';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'c4_app') THEN
    CREATE ROLE c4_app LOGIN PASSWORD 'devpass';
  END IF;

  -- Read-only roles
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'c2_reader') THEN
    CREATE ROLE c2_reader LOGIN PASSWORD 'devpass';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'c3_reader') THEN
    CREATE ROLE c3_reader LOGIN PASSWORD 'devpass';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'c4_reader') THEN
    CREATE ROLE c4_reader LOGIN PASSWORD 'devpass';
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- Schema ownership. The owner role controls DDL (Alembic migrations) for its
-- own schema and is the default owner of objects created there.
-- ---------------------------------------------------------------------------
ALTER SCHEMA c1 OWNER TO c1_app;
ALTER SCHEMA c2 OWNER TO c2_app;
ALTER SCHEMA c3 OWNER TO c3_app;
ALTER SCHEMA c4 OWNER TO c4_app;

-- Let each app create and use objects within its own schema.
GRANT USAGE, CREATE ON SCHEMA c1 TO c1_app;
GRANT USAGE, CREATE ON SCHEMA c2 TO c2_app;
GRANT USAGE, CREATE ON SCHEMA c3 TO c3_app;
GRANT USAGE, CREATE ON SCHEMA c4 TO c4_app;

-- ---------------------------------------------------------------------------
-- Cross-schema USAGE grants (per contracts 5.1 "Read-only roles granted").
--   c1  -> read by c2_reader (houses, rooms only), c3_reader, c4_reader
--   c2  -> read by c3_reader
--   c4  -> read by c2_reader (settings + contacts only), c3_reader
--   c3  -> no external readers
-- USAGE on the schema is required before any table SELECT grant is effective.
-- ---------------------------------------------------------------------------
GRANT USAGE ON SCHEMA c1 TO c2_reader, c3_reader, c4_reader;
GRANT USAGE ON SCHEMA c2 TO c3_reader;
GRANT USAGE ON SCHEMA c4 TO c2_reader, c3_reader;

-- ---------------------------------------------------------------------------
-- Default privileges so that tables CREATED LATER by each owner's migrations
-- automatically grant SELECT to the documented readers. Table-level SELECT on
-- already-existing tables is (re)applied by each service after its migrations;
-- these ALTER DEFAULT PRIVILEGES lines cover tables created from now on.
--
-- NOTE on contract nuance: c2_reader is only entitled to c1.houses/c1.rooms and
-- c4.house_service_settings/c4.emergency_contacts, and c3_reader must not see
-- password_hash/secret_hash in c4 (a c4.users_public view is used instead).
-- Column/table-level restriction is enforced by the owning service's migration
-- (it grants SELECT only on the permitted tables/view), not here. These broad
-- defaults are a convenience for dev; the owning migrations are authoritative.
-- ---------------------------------------------------------------------------

-- c1 tables readable by c2_reader, c3_reader, c4_reader
ALTER DEFAULT PRIVILEGES FOR ROLE c1_app IN SCHEMA c1
  GRANT SELECT ON TABLES TO c2_reader, c3_reader, c4_reader;

-- c2 tables readable by c3_reader
ALTER DEFAULT PRIVILEGES FOR ROLE c2_app IN SCHEMA c2
  GRANT SELECT ON TABLES TO c3_reader;

-- c4 tables readable by c2_reader and c3_reader (service migration narrows this)
ALTER DEFAULT PRIVILEGES FOR ROLE c4_app IN SCHEMA c4
  GRANT SELECT ON TABLES TO c2_reader, c3_reader;

-- Apply SELECT to any tables that already exist at bootstrap time (none on a
-- fresh DB, but keeps the script correct when re-run after migrations).
GRANT SELECT ON ALL TABLES IN SCHEMA c1 TO c2_reader, c3_reader, c4_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA c2 TO c3_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA c4 TO c2_reader, c3_reader;
