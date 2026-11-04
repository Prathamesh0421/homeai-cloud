#!/usr/bin/env bash
# HomeAI Cloud — LocalStack bootstrap (local dev only).
# Owner: Renuka (P0-5). Source of truth: docs/03_REPO_AND_INFRA.md section 5,
# docs/02_CONTRACTS.md section 5.3.
#
# LocalStack runs every executable script in /etc/localstack/init/ready.d/ once
# the edge gateway is ready. This script creates the S3 bucket and the three
# Secrets Manager secrets the stack expects. It uses `awslocal` (preinstalled in
# the localstack/localstack:3 image) which targets the local endpoint.
#
# Idempotent: creating an existing bucket/secret is tolerated (we check first).
set -euo pipefail

BUCKET="${S3_BUCKET:-homeai-local}"
REGION="${AWS_DEFAULT_REGION:-us-west-2}"

echo "[localstack-init] region=${REGION} bucket=${BUCKET}"

# ---------------------------------------------------------------------------
# S3: the clips/models/backups bucket.
# ---------------------------------------------------------------------------
if awslocal s3api head-bucket --bucket "${BUCKET}" 2>/dev/null; then
  echo "[localstack-init] bucket ${BUCKET} already exists"
else
  # us-east-1 must omit LocationConstraint; every other region requires it.
  if [ "${REGION}" = "us-east-1" ]; then
    awslocal s3api create-bucket --bucket "${BUCKET}"
  else
    awslocal s3api create-bucket --bucket "${BUCKET}" \
      --create-bucket-configuration "LocationConstraint=${REGION}"
  fi
  echo "[localstack-init] created bucket ${BUCKET}"
fi

# Default encryption (SSE-S3) to mirror the AWS bucket policy.
awslocal s3api put-bucket-encryption --bucket "${BUCKET}" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' \
  >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# Secrets Manager.
# ---------------------------------------------------------------------------
create_or_update_secret() {
  local name="$1"
  local value="$2"
  if awslocal secretsmanager describe-secret --secret-id "${name}" >/dev/null 2>&1; then
    awslocal secretsmanager put-secret-value --secret-id "${name}" --secret-string "${value}" >/dev/null
    echo "[localstack-init] updated secret ${name}"
  else
    awslocal secretsmanager create-secret --name "${name}" --secret-string "${value}" >/dev/null
    echo "[localstack-init] created secret ${name}"
  fi
}

# JWT signing key: a 2048-bit RSA private key in PEM form for C4 to sign tokens.
# Generated fresh at bootstrap (dev only; AWS uses a pre-provisioned secret).
JWT_PEM="$(openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 2>/dev/null)"
create_or_update_secret "homeai/jwt-signing-key" "${JWT_PEM}"

# Alert-view HMAC key: 32 random bytes, base64-encoded (C2 signs alert links).
HMAC_KEY="$(openssl rand -base64 32)"
create_or_update_secret "homeai/alert-view-hmac" "${HMAC_KEY}"

# Service client secrets: JSON matching the SERVICE_CLIENT_SECRET_* in .env.example.
SERVICE_CLIENTS_JSON=$(cat <<'JSON'
{
  "c2-alerts": "dev-c2-secret",
  "c3-data": "dev-c3-secret",
  "c3-worker": "dev-c3-secret",
  "c4-dashboard": "dev-c4-secret",
  "device-uploader": "dev-device-secret"
}
JSON
)
create_or_update_secret "homeai/service-clients" "${SERVICE_CLIENTS_JSON}"

echo "[localstack-init] done: S3 bucket + secrets ready"
