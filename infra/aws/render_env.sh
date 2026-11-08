#!/usr/bin/env bash
# HomeAI Cloud — render a production .env for the EC2 host.
# Owner: Mohit (C4-16). Source of truth: docs/03_REPO_AND_INFRA.md section 8.
#
# Run on the EC2 host (or anywhere with the AWS CLI + an instance profile) and
# redirect the output to .env:
#
#   infra/aws/render_env.sh > .env
#
# Reads the resources already provisioned per 03 §8 (S3 bucket, RDS endpoint,
# Secrets Manager secret names) and prints a .env suitable for the prod
# compose overlay. The IAM role on the EC2 instance provides AWS credentials;
# never put static keys in .env.
#
# Required env vars (set these before running, or pass as arguments):
#   RDS_ENDPOINT   — host:port of the RDS instance, e.g. db.xxxxxx.us-west-2.rds.amazonaws.com:5432
#   MONGO_HOST     — host:port of the Mongo container on EC2 (default localhost:27017)
#   SITE_ADDRESS   — public domain for Caddy TLS, e.g. homeai.duckdns.org
#   PUBLIC_BASE_URL — https://<SITE_ADDRESS>
#   S3_BUCKET       — the provisioned bucket name (default homeai-<team>-<accountid>)
#   TEAM            — short team tag used in the bucket name
#
# Optional:
#   AWS_REGION      — defaults to us-west-2
#   DB_NAME         — defaults to homeai
#   DB_MASTER_USER  — defaults to postgres (the RDS master user; password comes from Secrets Manager)

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-west-2}"
DB_NAME="${DB_NAME:-homeai}"
DB_MASTER_USER="${DB_MASTER_USER:-postgres}"
MONGO_HOST="${MONGO_HOST:-localhost:27017}"
SITE_ADDRESS="${SITE_ADDRESS:-:80}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-http://localhost:8080}"

if [ -z "${RDS_ENDPOINT:-}" ]; then
  echo "render_env.sh: RDS_ENDPOINT is required (host:port of the RDS instance)" >&2
  exit 1
fi
if [ -z "${TEAM:-}" ]; then
  echo "render_env.sh: TEAM is required (used in the S3 bucket name)" >&2
  exit 1
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text --region "${AWS_REGION}")"
S3_BUCKET="${S3_BUCKET:-homeai-${TEAM}-${ACCOUNT_ID}}"

# Fetch the RDS master password from Secrets Manager so we never inline it.
# Each component role password is fetched lazily by the service from
# homeai/db/<role>; here we only need the master to run init.sql once.
DB_MASTER_SECRET="${DB_MASTER_SECRET:-homeai/db/master}"
DB_MASTER_PASSWORD="$(aws secretsmanager get-secret-value --secret-id "${DB_MASTER_SECRET}" --query SecretString --output text --region "${AWS_REGION}")"

cat <<EOF
# HomeAI Cloud — production .env rendered by infra/aws/render_env.sh
# Do not commit. Regenerate after provisioning changes.

ENV=prod
PUBLIC_BASE_URL=${PUBLIC_BASE_URL}
SITE_ADDRESS=${SITE_ADDRESS}
DEMO_MODE=1

# AWS — real services (no LocalStack endpoint). The EC2 instance role provides
# credentials; AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY are intentionally unset.
AWS_REGION=${AWS_REGION}
# AWS_ENDPOINT_URL is empty on AWS (LocalStack only)
AWS_ENDPOINT_URL=
S3_BUCKET=${S3_BUCKET}

# Inter-service URLs (compose hostnames inside the EC2 docker network)
JWKS_URL=http://c4-dashboard:8004/.well-known/jwks.json
C4_BASE_URL=http://c4-dashboard:8004
C1_BASE_URL=http://c1-iot:8001
C2_BASE_URL=http://c2-alerts:8002
C3_BASE_URL=http://c3-data:8003

# PostgreSQL — RDS. Each service connects as its cX_app role; the password is
# fetched from Secrets Manager (homeai/db/<role>) by the service at startup.
# These URLs use the master user only for the one-time init.sql run; the
# services override DB user/password via their own settings.
DATABASE_URL_C2=postgresql+psycopg://${DB_MASTER_USER}:${DB_MASTER_PASSWORD}@${RDS_ENDPOINT}/${DB_NAME}
DATABASE_READER_URL_C2=postgresql+psycopg://c2_reader:\${C2_READER_PASSWORD}@${RDS_ENDPOINT}/${DB_NAME}
DATABASE_URL_C4=postgresql+psycopg://c4_app:\${C4_APP_PASSWORD}@${RDS_ENDPOINT}/${DB_NAME}

# MongoDB — container on the EC2 host (real Mongo, not DocumentDB)
MONGO_URL_C2_READER=mongodb://c2_reader:\${C2_READER_PASSWORD}@${MONGO_HOST}/homeai?authSource=homeai
MONGO_URL_C4=mongodb://c4_app:\${C4_APP_PASSWORD}@${MONGO_HOST}/homeai?authSource=homeai

# C4 JWT signing key (Secrets Manager id; the service fetches the PEM)
C4_JWT_PRIVATE_KEY_SECRET=homeai/jwt-signing-key

# Service client secrets — fetched from homeai/service-clients by C4 at startup.
# The names are stable; the values live in Secrets Manager.
SERVICE_CLIENT_SECRET_C2=\${SERVICE_CLIENT_SECRET_C2}
SERVICE_CLIENT_SECRET_C3=\${SERVICE_CLIENT_SECRET_C3}
SERVICE_CLIENT_SECRET_C4=\${SERVICE_CLIENT_SECRET_C4}
SERVICE_CLIENT_SECRET_DEVICE=\${SERVICE_CLIENT_SECRET_DEVICE}

# C2 alert-view HMAC (Secrets Manager id)
C2_ALERT_VIEW_KEY_SECRET=homeai/alert-view-hmac

# Notifier — real SNS on AWS
NOTIFIER=sns

# C3 model directory (mounted volume on EC2)
C3_MODEL_DIR=/models
EOF

# Helper note printed to stderr (not into .env)
cat >&2 <<EOF

# ---------------------------------------------------------------------------
# After generating .env, populate the role passwords from Secrets Manager:
#   C4_APP_PASSWORD=\$(aws secretsmanager get-secret-value --secret-id homeai/db/c4_app --query SecretString --output text)
#   C2_READER_PASSWORD=\$(aws secretsmanager get-secret-value --secret-id homeai/db/c2_reader --query SecretString --output text)
#   ...and the service-client secrets from homeai/service-clients
# Or run each service with its own secret-id env var and let it fetch at startup.
# ---------------------------------------------------------------------------
EOF
