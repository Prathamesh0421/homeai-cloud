#!/usr/bin/env bash
# C2's full test suite with coverage against real Postgres, Mongo and LocalStack, as CI runs it
# (`make test-c2-full`; the demo's "unit tests running" step).
#
# Starts three throwaway containers on non-default ports (or reuses them), so it runs next to
# the local stack or another project's Postgres on 5432. A missing store is a failure, not a
# skip (CI=true), so the coverage shown never comes from skipped tests.
#
#   scripts/test_c2.sh                       # all tests + coverage (extra args go to pytest)
#   scripts/test_c2.sh -k rule_engine        # a subset
#   C2_TEST_DOWN=1 scripts/test_c2.sh        # remove the containers afterwards
#
# Ports: C2_TEST_PG_PORT (55433), C2_TEST_MONGO_PORT (57017), C2_TEST_LS_PORT (54566).

set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
PG_PORT="${C2_TEST_PG_PORT:-55433}"
MONGO_PORT="${C2_TEST_MONGO_PORT:-57017}"
LS_PORT="${C2_TEST_LS_PORT:-54566}"

ensure() {  # name, then docker run args
  local name="$1"
  shift
  if [ -n "$(docker ps -q -f "name=^${name}$")" ]; then
    return
  elif [ -n "$(docker ps -aq -f "name=^${name}$")" ]; then
    docker start "${name}" >/dev/null
  else
    docker run -d --name "${name}" "$@" >/dev/null
  fi
  echo "[test-c2] started ${name}"
}

wait_for() {  # description, then a command that succeeds when ready
  local what="$1"
  shift
  for _ in $(seq 1 60); do
    if "$@" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  echo "[test-c2] ${what} did not become ready" >&2
  exit 1
}

ensure c2test-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=homeai_test \
  -p "${PG_PORT}:5432" postgres:16
ensure c2test-mongo -p "${MONGO_PORT}:27017" mongo:7
ensure c2test-ls -e SERVICES=s3,sns,secretsmanager -p "${LS_PORT}:4566" localstack/localstack:3

wait_for Postgres docker exec c2test-pg pg_isready -U postgres -d homeai_test
wait_for Mongo docker exec c2test-mongo mongosh --quiet --eval "db.adminCommand({ping: 1})"
wait_for LocalStack curl -fsS "http://localhost:${LS_PORT}/_localstack/health"

# Same bootstrap as CI and the stack: schemas, cX_app / cX_reader roles, grants (idempotent).
docker exec -i c2test-pg psql -q -v ON_ERROR_STOP=1 -U postgres -d homeai_test \
  < infra/db/init.sql 2>&1 | { grep -v NOTICE || true; }

PG="postgresql+psycopg://postgres:postgres@localhost:${PG_PORT}/homeai_test"
export CI=true ENV=test DEMO_MODE=1 AWS_REGION=us-west-2 \
  AWS_ENDPOINT_URL="http://localhost:${LS_PORT}" AWS_ACCESS_KEY_ID=test \
  AWS_SECRET_ACCESS_KEY=test PGPASSWORD=postgres \
  DATABASE_URL_C2="${PG}" DATABASE_READER_URL_C2="${PG}" \
  MONGO_URL_C2_READER="mongodb://localhost:${MONGO_PORT}/homeai_test"

status=0
(cd services/c2_alerts && "${PYTHON}" -m pytest -q -p no:cacheprovider \
  --cov=app --cov-report=term-missing:skip-covered --cov-fail-under=80 "$@") || status=$?

if [ -n "${C2_TEST_DOWN:-}" ]; then
  docker rm -f c2test-pg c2test-mongo c2test-ls >/dev/null
  echo "[test-c2] removed the test containers"
fi
exit "${status}"
