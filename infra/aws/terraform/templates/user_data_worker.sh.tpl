#!/usr/bin/env bash
# HomeAI Cloud — Worker ASG user-data (A-4).
# Runs only c3-worker (YAMNet). No Caddy / ALB registration.
#
# Required Secrets Manager material: same as user_data_api.sh.tpl
# (DB + Mongo/Atlas URLs, JWT not required for worker beyond what .env needs,
# service-clients for SERVICE_CLIENT_SECRET_C3 → C2 evaluate).
#
# Prefer homeai/runtime-env once Atlas (A-2) is live so API and worker share one blob.

set -euo pipefail
exec > >(tee -a /var/log/homeai-user-data.log) 2>&1
echo "[user-data-worker] start $(date -u +%Y-%m-%dT%H:%MZ)"

export DEBIAN_FRONTEND=noninteractive
AWS_REGION="${aws_region}"
ACCOUNT_ID="${account_id}"
ECR_REGISTRY="$${ACCOUNT_ID}.dkr.ecr.$${AWS_REGION}.amazonaws.com"
IMAGE_TAG="${ecr_image_tag}"
PROJECT="${project_name}"
APP_DIR="/opt/homeai-cloud"
LOG_GROUP="${log_group_base}/user-data"

# ---------------------------------------------------------------------------
# 1. Packages (idempotent)
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
            "log_stream_name": "{instance_id}-worker"
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
# 2. Repo + .env
# ---------------------------------------------------------------------------
if [ ! -d "$${APP_DIR}/.git" ]; then
  git clone --depth 1 --branch "${repo_ref}" "${repo_clone_url}" "$${APP_DIR}"
else
  git -C "$${APP_DIR}" fetch --depth 1 origin "${repo_ref}"
  git -C "$${APP_DIR}" checkout -f "FETCH_HEAD" || git -C "$${APP_DIR}" pull --ff-only
fi
cd "$${APP_DIR}"

secret() {
  aws secretsmanager get-secret-value --secret-id "$1" --region "$${AWS_REGION}" \
    --query SecretString --output text
}

if aws secretsmanager describe-secret --secret-id "${secrets_prefix}/runtime-env" --region "$${AWS_REGION}" >/dev/null 2>&1; then
  secret "${secrets_prefix}/runtime-env" > "$${APP_DIR}/.env"
else
  export TEAM="${team}"
  export AWS_REGION
  export S3_BUCKET="${s3_bucket}"
  export SITE_ADDRESS=":80"
  export PUBLIC_BASE_URL="https://${domain_name}"
  %{ if rds_endpoint != "" ~}
  export RDS_ENDPOINT="${rds_endpoint}:5432"
  %{ else ~}
  export SKIP_RDS=1
  %{ endif ~}
  bash infra/aws/render_env.sh > "$${APP_DIR}/.env"
  sed -i 's/^DEMO_MODE=.*/DEMO_MODE=0/' "$${APP_DIR}/.env" || true
fi

{
  echo ""
  echo "# --- Tier-2 ECR tags (user-data worker) ---"
  echo "ECR_REGISTRY=$${ECR_REGISTRY}"
  echo "IMAGE_TAG=$${IMAGE_TAG}"
  # Worker container uses the c3-data image (same Dockerfile); prefer c3-worker repo tag.
  echo "C3_WORKER_IMAGE=$${ECR_REGISTRY}/$${PROJECT}/c3-worker:$${IMAGE_TAG}"
  echo "C3_IMAGE=$${ECR_REGISTRY}/$${PROJECT}/c3-data:$${IMAGE_TAG}"
} >> "$${APP_DIR}/.env"
chmod 600 "$${APP_DIR}/.env"

# ---------------------------------------------------------------------------
# 3. ECR login + worker only
# ---------------------------------------------------------------------------
aws ecr get-login-password --region "$${AWS_REGION}" \
  | docker login --username AWS --password-stdin "$${ECR_REGISTRY}"

docker pull "$${ECR_REGISTRY}/$${PROJECT}/c3-worker:$${IMAGE_TAG}" \
  || docker pull "$${ECR_REGISTRY}/$${PROJECT}/c3-data:$${IMAGE_TAG}" \
  || echo "[warn] ECR pull failed — falling back to --build (slow on boot)"

COMPOSE=(docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml)
# Worker hosts: no mongo/caddy when Atlas is configured (A-2). Until then, start
# mongo only if MONGO_HOST still points at the compose service name.
# Prefer --profile worker once S-1 lands; today use explicit service + c3 profile.
"$${COMPOSE[@]}" --profile c3 up -d --no-build c3-worker \
  || "$${COMPOSE[@]}" --profile c3 up -d --build c3-worker

echo "[user-data-worker] done $(date -u +%Y-%m-%dT%H:%MZ)"
