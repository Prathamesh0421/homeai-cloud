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
-- Table-level SELECT.
--
-- Where a reader may see every table of a schema, default privileges grant it
-- for tables the owner's migrations create later, and GRANT ... ON ALL TABLES
-- covers tables that already exist when this script is re-run.
--
-- Where a reader may see only some tables, the OWNING MIGRATION grants exactly
-- those tables (contracts 5.1), because tables do not exist yet when this runs:
--   c2_reader on c1: houses, rooms                       -> C1 migration (Ekant)
--   c2_reader on c4: house_service_settings,
--                    emergency_contacts                  -> C4 migration 0002
--   c3_reader on c4: everything except password_hash /
--                    secret_hash (users_public view)      -> C4 migration 0002
-- No default privileges are set for those, so a new c1/c4 table is never
-- readable by them by accident.
-- ---------------------------------------------------------------------------

-- ALTER DEFAULT PRIVILEGES FOR ROLE x requires the current user to be a member
-- of x (or a true superuser). Local Docker postgres is a superuser; AWS RDS
-- master is not. Grant membership so this works on both. Idempotent. This does
-- NOT give cX_app any of the master's privileges — only the reverse (master can
-- act as those roles for bootstrap).
GRANT c1_app, c2_app, c4_app TO CURRENT_USER;

-- c1 tables readable by c3_reader and c4_reader
ALTER DEFAULT PRIVILEGES FOR ROLE c1_app IN SCHEMA c1
  GRANT SELECT ON TABLES TO c3_reader, c4_reader;

-- c2 tables readable by c3_reader
ALTER DEFAULT PRIVILEGES FOR ROLE c2_app IN SCHEMA c2
  GRANT SELECT ON TABLES TO c3_reader;

-- An earlier version of this script also gave c2_reader every c1/c4 table and
-- c3_reader every c4 table by default; remove that from databases it bootstrapped.
-- (Existing table grants are narrowed by the owning migrations, not here: a
-- REVOKE on all tables would undo their grants whenever this script is re-run.)
ALTER DEFAULT PRIVILEGES FOR ROLE c1_app IN SCHEMA c1
  REVOKE SELECT ON TABLES FROM c2_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE c4_app IN SCHEMA c4
  REVOKE SELECT ON TABLES FROM c2_reader, c3_reader;

-- Apply SELECT to any tables that already exist at bootstrap time (none on a
-- fresh DB, but keeps the script correct when re-run after migrations).
GRANT SELECT ON ALL TABLES IN SCHEMA c1 TO c3_reader, c4_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA c2 TO c3_reader;
