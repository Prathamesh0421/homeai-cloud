#!/usr/bin/env bash
# HomeAI Cloud — give the database roles and Mongo users their Secrets Manager passwords.
# Owner: Mohit (C4-16). Run on the EC2 host; `make deploy` calls it after the data layer is up
# and before the services start.
#
# infra/db/init.sql and infra/mongo/init.js create every role/user with the dev password.
# render_env.sh writes the Secrets Manager passwords (homeai/db/<role>, homeai/mongo/<user>)
# into .env, so the roles and users must be set to the same values. Safe to re-run.
#
# Env:
#   SKIP_RDS=1    — Postgres runs as the compose container (else RDS, needs RDS_ENDPOINT)
#   RDS_ENDPOINT  — host:port of the RDS instance (RDS only)
#   AWS_REGION    — defaults to us-west-2
#   DB_NAME, DB_MASTER_USER — default homeai / postgres
#   COMPOSE_PROD  — compose command (default: base + prod overlay, as in the Makefile)

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-west-2}"
DB_NAME="${DB_NAME:-homeai}"
DB_MASTER_USER="${DB_MASTER_USER:-postgres}"
# Same compose command as the Makefile (COMPOSE_PROD), so `make deploy` and this script agree.
read -r -a COMPOSE <<< "${COMPOSE_PROD:-docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml}"
PG_ROLES=(c1_app c2_app c2_reader c3_app c3_reader c4_app c4_reader)
MONGO_USERS=(c1_app c2_reader c3_app c4_app)

secret() {
  aws secretsmanager get-secret-value --secret-id "$1" --query SecretString --output text \
    --region "${AWS_REGION}"
}
has_secret() {
  aws secretsmanager describe-secret --secret-id "$1" --region "${AWS_REGION}" >/dev/null 2>&1
}

# --- PostgreSQL -----------------------------------------------------------------------------
# Statements go through stdin so the passwords never appear in a process list.
sql=""
for role in "${PG_ROLES[@]}"; do
  pw="$(secret "homeai/db/${role}")"
  sql+="ALTER ROLE ${role} PASSWORD '${pw//\'/\'\'}';"$'\n'
done
if [ -n "${SKIP_RDS:-}" ]; then
  printf '%s' "${sql}" | "${COMPOSE[@]}" --profile local-postgres-fallback exec -T postgres \
    psql -q -v ON_ERROR_STOP=1 -U postgres -d "${DB_NAME}"
else
  : "${RDS_ENDPOINT:?RDS_ENDPOINT is required (host:port of the RDS instance), or set SKIP_RDS=1}"
  printf '%s' "${sql}" | PGPASSWORD="$(secret homeai/db/master)" psql -q -v ON_ERROR_STOP=1 \
    -h "${RDS_ENDPOINT%:*}" -p "${RDS_ENDPOINT##*:}" -U "${DB_MASTER_USER}" -d "${DB_NAME}"
fi
echo "[set_passwords] postgres: ${#PG_ROLES[@]} role passwords set"

# --- MongoDB (container) --------------------------------------------------------------------
mongosh_root() {  # extra docker exec args..., then the --eval script as the last argument
  local script="${*: -1}"
  "${COMPOSE[@]}" exec -T "${@:1:$#-1}" mongo mongosh --quiet -u root -p root \
    --authenticationDatabase admin --eval "${script}"
}
# init.js creates the users on the first start of a fresh volume; wait until it has.
for _ in $(seq 1 30); do
  if [ "$(mongosh_root "print(db.getSiblingDB('homeai').getUser('c2_reader') !== null)")" = "true" ]; then
    break
  fi
  sleep 2
done
set_count=0
for user in "${MONGO_USERS[@]}"; do
  if ! has_secret "homeai/mongo/${user}"; then
    echo "[set_passwords] mongo: no secret homeai/mongo/${user}; ${user} keeps the dev password" >&2
    continue
  fi
  NEW_PW="$(secret "homeai/mongo/${user}")" mongosh_root -e NEW_PW \
    "db.getSiblingDB('homeai').updateUser('${user}', { pwd: process.env.NEW_PW })"
  set_count=$((set_count + 1))
done
echo "[set_passwords] mongo: ${set_count} user passwords set"
