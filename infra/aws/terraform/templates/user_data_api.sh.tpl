#!/usr/bin/env bash
# HomeAI Cloud — API ASG user-data (A-4).
# Runs Caddy + c4/c1/c2/c3-data (no c3-worker). Idempotent: safe on reboot if
# cloud-init re-runs partially; compose up is declarative.
#
# Required Secrets Manager material (same names as provision.sh / render_env.sh):
#   homeai/db/c1_app, c2_app, c2_reader, c3_app, c3_reader, c4_app
#   homeai/mongo/c1_app, c2_reader, c3_app, c4_app   (or Atlas URLs once A-2 lands)
#   homeai/jwt-signing-key
#   homeai/alert-view-hmac
#   homeai/service-clients   (JSON map of client_id → plaintext secret)
# Optional override secret (recommended for Tier 2):
#   homeai/runtime-env       (full .env body). If present, used as-is and the
#                            render step below is skipped.
#
# Template vars injected by Terraform:
#   aws_region, account_id, project_name, ecr_image_tag, s3_bucket,
#   rds_endpoint, secrets_prefix, domain_name, team, repo_clone_url,
#   repo_ref, environment, log_group_base

set -euo pipefail
exec > >(tee -a /var/log/homeai-user-data.log) 2>&1
echo "[user-data-api] start $(date -u +%Y-%m-%dT%H:%MZ)"

export DEBIAN_FRONTEND=noninteractive
AWS_REGION="${aws_region}"
ACCOUNT_ID="${account_id}"
ECR_REGISTRY="$${ACCOUNT_ID}.dkr.ecr.$${AWS_REGION}.amazonaws.com"
IMAGE_TAG="${ecr_image_tag}"
PROJECT="${project_name}"
APP_DIR="/opt/homeai-cloud"
LOG_GROUP="${log_group_base}/user-data"

# ---------------------------------------------------------------------------
# 1. Packages — Docker Engine + Compose plugin + AWS CLI + CloudWatch agent
# ---------------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg unzip git jq
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable --now docker
fi

if ! command -v aws >/dev/null 2>&1; then
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
  unzip -q /tmp/awscliv2.zip -d /tmp && /tmp/aws/install
fi

# CloudWatch agent (basic mem/disk + log file). Failures here must not block boot.
if [ ! -x /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl ]; then
  curl -fsSL "https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb" \
    -o /tmp/amazon-cloudwatch-agent.deb || true
  dpkg -i /tmp/amazon-cloudwatch-agent.deb || true
fi

cat >/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json <<CWJSON || true
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/homeai-user-data.log",
            "log_group_name": "$${LOG_GROUP}",
            "log_stream_name": "{instance_id}"
          }
        ]
      }
    }
  },
  "metrics": {
    "namespace": "HomeAI/EC2",
    "metrics_collected": {
      "mem": { "measurement": ["mem_used_percent"] },
      "disk": { "measurement": ["used_percent"], "resources": ["/"] }
    }
  }
}
CWJSON
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -s \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json || true

# ---------------------------------------------------------------------------
# 2. Repo checkout (compose + Caddy files only; images come from ECR)
# ---------------------------------------------------------------------------
if [ ! -d "$${APP_DIR}/.git" ]; then
  git clone --depth 1 --branch "${repo_ref}" "${repo_clone_url}" "$${APP_DIR}"
else
  git -C "$${APP_DIR}" fetch --depth 1 origin "${repo_ref}"
  git -C "$${APP_DIR}" checkout -f "FETCH_HEAD" || git -C "$${APP_DIR}" pull --ff-only
fi
cd "$${APP_DIR}"

# ---------------------------------------------------------------------------
# 3. .env from Secrets Manager
# ---------------------------------------------------------------------------
secret() {
  aws secretsmanager get-secret-value --secret-id "$1" --region "$${AWS_REGION}" \
    --query SecretString --output text
}

if aws secretsmanager describe-secret --secret-id "${secrets_prefix}/runtime-env" --region "$${AWS_REGION}" >/dev/null 2>&1; then
  echo "[user-data-api] using ${secrets_prefix}/runtime-env"
  secret "${secrets_prefix}/runtime-env" > "$${APP_DIR}/.env"
else
  echo "[user-data-api] rendering .env via render_env.sh"
  export TEAM="${team}"
  export AWS_REGION
  export S3_BUCKET="${s3_bucket}"
  export SITE_ADDRESS=":80"
  export PUBLIC_BASE_URL="https://${domain_name}"
  %{ if rds_endpoint != "" ~}
  export RDS_ENDPOINT="${rds_endpoint}:5432"
  %{ else ~}
  # No RDS endpoint in Terraform vars — expect Atlas/Mongo + RDS to be baked into runtime-env later.
  export SKIP_RDS=1
  %{ endif ~}
  # After A-2, set MONGO_HOST to the Atlas connection host or put full URLs in runtime-env.
  bash infra/aws/render_env.sh > "$${APP_DIR}/.env"
  # Tier-2 default: DEMO_MODE off outside rehearsals (A-0). Flip in runtime-env for the live demo.
  sed -i 's/^DEMO_MODE=.*/DEMO_MODE=0/' "$${APP_DIR}/.env" || true
fi

# Point compose at ECR tags (override build:). Requires Renuka S-1 image: lines or
# a small overlay; until then we export IMAGE_* for a future compose override.
{
  echo ""
  echo "# --- Tier-2 ECR tags (user-data) ---"
  echo "ECR_REGISTRY=$${ECR_REGISTRY}"
  echo "IMAGE_TAG=$${IMAGE_TAG}"
  echo "C1_IMAGE=$${ECR_REGISTRY}/$${PROJECT}/c1-iot:$${IMAGE_TAG}"
  echo "C2_IMAGE=$${ECR_REGISTRY}/$${PROJECT}/c2-alerts:$${IMAGE_TAG}"
  echo "C3_IMAGE=$${ECR_REGISTRY}/$${PROJECT}/c3-data:$${IMAGE_TAG}"
  echo "C4_IMAGE=$${ECR_REGISTRY}/$${PROJECT}/c4-dashboard:$${IMAGE_TAG}"
  echo "WEB_IMAGE=$${ECR_REGISTRY}/$${PROJECT}/web:$${IMAGE_TAG}"
} >> "$${APP_DIR}/.env"

chmod 600 "$${APP_DIR}/.env"

# ---------------------------------------------------------------------------
# 4. ECR login + pull + compose up (API profile)
# ---------------------------------------------------------------------------
aws ecr get-login-password --region "$${AWS_REGION}" \
  | docker login --username AWS --password-stdin "$${ECR_REGISTRY}"

# Pull best-effort so a missing tag does not leave the instance permanently dead
# before the first CI push; compose will still fail health until images exist.
for img in c1-iot c2-alerts c3-data c4-dashboard web; do
  docker pull "$${ECR_REGISTRY}/$${PROJECT}/$${img}:$${IMAGE_TAG}" || echo "[warn] pull failed for $${img}"
done

COMPOSE=(docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml)
# API tier: gateway + app services. Prefer explicit service list so c3-worker
# (same profile "c3" today) is not started on API hosts. When S-1 adds an
# `api` profile, switch to: --profile api up -d
"$${COMPOSE[@]}" --profile gateway --profile c1 --profile c3 \
  up -d --no-build \
  mongo caddy c4-dashboard c1-iot c2-alerts c3-data \
  || "$${COMPOSE[@]}" --profile gateway --profile c1 --profile c3 up -d --build \
       mongo caddy c4-dashboard c1-iot c2-alerts c3-data

echo "[user-data-api] done $(date -u +%Y-%m-%dT%H:%MZ)"
