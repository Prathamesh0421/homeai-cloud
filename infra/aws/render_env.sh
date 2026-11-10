#!/usr/bin/env bash
# HomeAI Cloud — render a production .env for the EC2 host.
# Owner: Mohit (C4-16). Source of truth: docs/03_REPO_AND_INFRA.md section 8.
#
# Run on the EC2 host (or anywhere with the AWS CLI + an instance profile) and
# redirect the output to .env:
#
#   RDS_ENDPOINT=db.xxx.rds.amazonaws.com:5432 TEAM=cmpe281 \
#     SITE_ADDRESS=:80 PUBLIC_BASE_URL=http://x.x.x.x \
#     make deploy-env > .env
#
# Fetches role passwords from Secrets Manager at render time so the .env has
# no ${PLACEHOLDER} strings (those break Docker Compose). `make deploy` then
# runs set_passwords.sh so Postgres roles and Mongo users match those values.
#
# Required:
#   TEAM            — short team tag used in the bucket name
#   RDS_ENDPOINT    — host:port of RDS (unless SKIP_RDS=1)
# Optional:
#   SITE_ADDRESS, PUBLIC_BASE_URL, S3_BUCKET, AWS_REGION, DB_NAME, MONGO_HOST
#   SKIP_RDS=1      — use the Postgres container (postgres:5432)

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-west-2}"
DB_NAME="${DB_NAME:-homeai}"
# Inside Compose, the mongo service DNS name is "mongo" (not localhost).
MONGO_HOST="${MONGO_HOST:-mongo:27017}"
SITE_ADDRESS="${SITE_ADDRESS:-:80}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-http://localhost:8080}"

if [ -n "${SKIP_RDS:-}" ]; then
  DB_HOST="postgres:5432"
elif [ -n "${RDS_ENDPOINT:-}" ]; then
  DB_HOST="${RDS_ENDPOINT}"
  case "${DB_HOST}" in
    *:*) ;;
    *) DB_HOST="${DB_HOST}:5432" ;;
  esac
else
  echo "render_env.sh: RDS_ENDPOINT is required (host:port), or set SKIP_RDS=1" >&2
  exit 1
fi
if [ -z "${TEAM:-}" ]; then
  echo "render_env.sh: TEAM is required (used in the S3 bucket name)" >&2
  exit 1
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text --region "${AWS_REGION}")"
S3_BUCKET="${S3_BUCKET:-homeai-${TEAM}-${ACCOUNT_ID}}"

secret() {
  aws secretsmanager get-secret-value --secret-id "$1" --query SecretString --output text \
    --region "${AWS_REGION}"
}
# Percent-encode a password for use inside a connection URL.
urlenc() {
  python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}
pg_url() {  # role
  echo "postgresql+psycopg://$1:$(urlenc "$(secret "homeai/db/$1")")@${DB_HOST}/${DB_NAME}"
}
mongo_url() {  # user
  echo "mongodb://$1:$(urlenc "$(secret "homeai/mongo/$1")")@${MONGO_HOST}/homeai?authSource=homeai"
}
client_secret() {  # client id in homeai/service-clients
  python3 -c 'import json, sys; print(json.loads(sys.argv[1])[sys.argv[2]])' "${CLIENTS_JSON}" "$1"
}

echo "[render_env] fetching secrets..." >&2
CLIENTS_JSON="$(secret homeai/service-clients)"

cat <<EOF
# HomeAI Cloud — production .env (rendered $(date -u +%Y-%m-%dT%H:%MZ))
# Do not commit. Regenerate after provisioning changes.

ENV=prod
PUBLIC_BASE_URL=${PUBLIC_BASE_URL}
SITE_ADDRESS=${SITE_ADDRESS}
DEMO_MODE=1

# AWS — real services (no LocalStack). Empty endpoint = use the real regional API.
# C4_AWS_ENDPOINT_URL clears C4's old LocalStack default when present.
AWS_REGION=${AWS_REGION}
AWS_ENDPOINT_URL=
C4_AWS_ENDPOINT_URL=
S3_BUCKET=${S3_BUCKET}

# Inter-service URLs (compose hostnames inside the EC2 docker network)
JWKS_URL=http://c4-dashboard:8004/.well-known/jwks.json
C4_BASE_URL=http://c4-dashboard:8004
C1_BASE_URL=http://c1-iot:8001
C2_BASE_URL=http://c2-alerts:8002
C3_BASE_URL=http://c3-data:8003

# PostgreSQL (${DB_HOST}). Passwords from Secrets Manager (set_passwords.sh applies them).
DATABASE_URL_C1=$(pg_url c1_app)
DATABASE_URL_C2=$(pg_url c2_app)
DATABASE_READER_URL_C2=$(pg_url c2_reader)
DATABASE_URL_C3=$(pg_url c3_app)
DATABASE_READER_URL_C3=$(pg_url c3_reader)
DATABASE_URL_C4=$(pg_url c4_app)

# MongoDB — container on the EC2 host (passwords aligned by set_passwords.sh)
MONGO_URL_C1=$(mongo_url c1_app)
MONGO_URL_C2_READER=$(mongo_url c2_reader)
MONGO_URL_C3=$(mongo_url c3_app)
MONGO_URL_C4=$(mongo_url c4_app)

# C4 JWT signing key (Secrets Manager id; the service fetches the PEM)
C4_JWT_PRIVATE_KEY_SECRET=homeai/jwt-signing-key

# Service client secrets (values from homeai/service-clients)
SERVICE_CLIENT_SECRET_C2=$(client_secret c2-alerts)
SERVICE_CLIENT_SECRET_C3=$(client_secret c3-worker)
SERVICE_CLIENT_SECRET_C4=$(client_secret c4-dashboard)
SERVICE_CLIENT_SECRET_DEVICE=$(client_secret device-uploader)

# C2 alert-view HMAC (Secrets Manager id)
C2_ALERT_VIEW_KEY_SECRET=homeai/alert-view-hmac

# Notifier — real SNS on AWS
NOTIFIER=sns

# C3 model directory (mounted volume on EC2)
C3_MODEL_DIR=/models
EOF

echo "[render_env] wrote env for bucket=${S3_BUCKET} rds=${DB_HOST} mongo=${MONGO_HOST}" >&2
