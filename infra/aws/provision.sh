#!/usr/bin/env bash
# HomeAI Cloud — one-time AWS provisioning for the demo (C4-16).
# Owner: Mohit. Source of truth: docs/03_REPO_AND_INFRA.md section 8,
# docs/07_DEMO_NOV_11.md section 5.
#
# Creates: S3 bucket, RDS instance, Secrets Manager secrets, IAM role + instance
# profile, EC2 + Elastic IP, and the security groups. Idempotent where the
# service supports it (S3, Secrets Manager, IAM); RDS/EC2 are created only if
# they do not exist (checked by name/tag).
#
# Run once from a machine with admin AWS credentials (not the EC2 host):
#
#   TEAM=cmpe281 REGION=us-west-2 KEY_NAME=mohit-demo \
#     infra/aws/provision.sh
#
# Required env vars:
#   TEAM       — short tag used in the bucket name (homeai-<team>-<accountid>)
#   KEY_NAME   — an existing EC2 key pair name for SSH access
# Optional:
#   REGION         — us-west-2 (default)
#   DB_INSTANCE    — homeai-db (default)
#   EC2_INSTANCE   — homeai-ec2 (default)
#   EC2_TYPE        — t3.large (default)
#   DB_TYPE         — db.t4g.micro (default)
#   DB_PASSWORD     — generated if not set
#   JWT_PEM         — generated if not set (2048-bit RSA)
#   SKIP_RDS=1      — provision everything except RDS (use the Postgres container fallback)

set -euo pipefail

REGION="${REGION:-us-west-2}"
TEAM="${TEAM:?TEAM is required (e.g. cmpe281)}"
KEY_NAME="${KEY_NAME:?KEY_NAME is required (an existing EC2 key pair)}"
DB_INSTANCE="${DB_INSTANCE:-homeai-db}"
EC2_INSTANCE="${EC2_INSTANCE:-homeai-ec2}"
EC2_TYPE="${EC2_TYPE:-t3.large}"
DB_TYPE="${DB_TYPE:-db.t4g.micro}"
DB_NAME="${DB_NAME:-homeai}"
DB_MASTER_USER="${DB_MASTER_USER:-postgres}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text --region "${REGION}")"
BUCKET="homeai-${TEAM}-${ACCOUNT_ID}"
echo "[provision] account=${ACCOUNT_ID} region=${REGION} bucket=${BUCKET}"

# ---------------------------------------------------------------------------
# 1. S3 bucket (Block Public Access, SSE-S3, lifecycle).
# ---------------------------------------------------------------------------
if aws s3api head-bucket --bucket "${BUCKET}" --region "${REGION}" 2>/dev/null; then
  echo "[provision] bucket ${BUCKET} exists"
else
  if [ "${REGION}" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}"
  else
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" \
      --create-bucket-configuration "LocationConstraint=${REGION}"
  fi
  aws s3api put-public-access-block --bucket "${BUCKET}" \
    --public-access-block-configuration \
    BlockPublicAcl=true,IgnorePublicAcl=true,BlockPublicPolicy=true,RestrictPublicBuckets=true \
    --region "${REGION}"
  aws s3api put-bucket-encryption --bucket "${BUCKET}" --region "${REGION}" \
    --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
  aws s3api put-bucket-lifecycle-configuration --bucket "${BUCKET}" --region "${REGION}" \
    --lifecycle-configuration file://infra/aws/s3-lifecycle.json
  echo "[provision] created bucket ${BUCKET}"
fi

# ---------------------------------------------------------------------------
# 2. Security groups.
# ---------------------------------------------------------------------------
EC2_SG_ID="$(aws ec2 describe-security-groups --group-names homeai-ec2 --query 'SecurityGroups[0].GroupId' --output text --region "${REGION}" 2>/dev/null || true)"
if [ -z "${EC2_SG_ID}" ]; then
  EC2_SG_ID="$(aws ec2 create-security-group --group-name homeai-ec2 \
    --description "HomeAI EC2 host" --region "${REGION}" --query GroupId --output text)"
  aws ec2 authorize-security-group-ingress --group-id "${EC2_SG_ID}" --region "${REGION}" \
    --ip-permissions IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges='[{CidrIp=0.0.0.0/0}]' \
                    IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges='[{CidrIp=0.0.0.0/0}]' \
                    IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges='[{CidrIp=0.0.0.0/0}]'
  echo "[provision] created SG homeai-ec2 (${EC2_SG_ID})"
fi

RDS_SG_ID="$(aws ec2 describe-security-groups --group-names homeai-rds --query 'SecurityGroups[0].GroupId' --output text --region "${REGION}" 2>/dev/null || true)"
if [ -z "${RDS_SG_ID}" ]; then
  RDS_SG_ID="$(aws ec2 create-security-group --group-name homeai-rds \
    --description "HomeAI RDS" --region "${REGION}" --query GroupId --output text)"
  aws ec2 authorize-security-group-ingress --group-id "${RDS_SG_ID}" --region "${REGION}" \
    --ip-permissions IpProtocol=tcp,FromPort=5432,ToPort=5432,UserIdentPairs='[{GroupId='${EC2_SG_ID}'}]'
  echo "[provision] created SG homeai-rds (${RDS_SG_ID})"
fi

# ---------------------------------------------------------------------------
# 3. Secrets Manager (idempotent: create or update).
# ---------------------------------------------------------------------------
DB_PASSWORD="${DB_PASSWORD:-$(openssl rand -base64 24)}"
JWT_PEM="${JWT_PEM:-$(openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 2>/dev/null)}"
HMAC_KEY="$(openssl rand -base64 32)"

upsert_secret() {
  local name="$1" value="$2"
  if aws secretsmanager describe-secret --secret-id "${name}" --region "${REGION}" >/dev/null 2>&1; then
    aws secretsmanager put-secret-value --secret-id "${name}" --secret-string "${value}" --region "${REGION}" >/dev/null
    echo "[provision] updated secret ${name}"
  else
    aws secretsmanager create-secret --name "${name}" --secret-string "${value}" --region "${REGION}" >/dev/null
    echo "[provision] created secret ${name}"
  fi
}

upsert_secret "homeai/db/master" "${DB_PASSWORD}"
upsert_secret "homeai/jwt-signing-key" "${JWT_PEM}"
upsert_secret "homeai/alert-view-hmac" "${HMAC_KEY}"
# Per-role DB passwords (services fetch their own at startup).
for role in c1_app c2_app c2_reader c3_app c3_reader c4_app c4_reader; do
  upsert_secret "homeai/db/${role}" "$(openssl rand -base64 24)"
done
# Mongo users (container on EC2).
for role in c2_reader c4_app; do
  upsert_secret "homeai/mongo/${role}" "$(openssl rand -base64 24)"
done
# Service client secrets (JSON; mirror localstack init-aws.sh).
SERVICE_CLIENTS_JSON='{"c2-alerts":"dev-c2-secret","c3-data":"dev-c3-secret","c3-worker":"dev-c3-secret","c4-dashboard":"dev-c4-secret","device-uploader":"dev-device-secret"}'
upsert_secret "homeai/service-clients" "${SERVICE_CLIENTS_JSON}"

# ---------------------------------------------------------------------------
# 4. IAM role + instance profile (least privilege, ec2-policy.json).
# ---------------------------------------------------------------------------
# Substitute the policy template with concrete ARNs.
POLICY_DOC="$(mktemp)"
sed -e "s|\${TEAM}|${TEAM}|g" \
    -e "s|\${ACCOUNT_ID}|${ACCOUNT_ID}|g" \
    -e "s|\${AWS_REGION}|${REGION}|g" \
    infra/aws/ec2-policy.json > "${POLICY_DOC}"

if aws iam get-role --role-name homeai-ec2-role --region "${REGION}" >/dev/null 2>&1; then
  echo "[provision] IAM role homeai-ec2-role exists"
else
  aws iam create-role --role-name homeai-ec2-role --region "${REGION}" \
    --assume-role-policy-document file://infra/aws/ec2-trust-policy.json >/dev/null
  aws iam put-role-policy --role-name homeai-ec2-role --policy-name homeai-ec2-policy \
    --policy-document file://"${POLICY_DOC}" --region "${REGION}"
  aws iam create-instance-profile --instance-profile-name homeai-ec2-profile --region "${REGION}"
  aws iam add-role-to-instance-profile --instance-profile-name homeai-ec2-profile \
    --role-name homeai-ec2-role --region "${REGION}"
  echo "[provision] created IAM role + instance profile"
fi
rm -f "${POLICY_DOC}"

# ---------------------------------------------------------------------------
# 5. RDS (skip with SKIP_RDS=1 to use the Postgres container fallback).
# ---------------------------------------------------------------------------
if [ -z "${SKIP_RDS:-}" ]; then
  if aws rds describe-db-instances --db-instance-identifier "${DB_INSTANCE}" --region "${REGION}" >/dev/null 2>&1; then
    echo "[provision] RDS ${DB_INSTANCE} exists"
  else
    aws rds create-db-instance \
      --db-instance-identifier "${DB_INSTANCE}" \
      --db-instance-class "${DB_TYPE}" \
      --engine postgres --engine-version 16 \
      --master-username "${DB_MASTER_USER}" --master-user-password "${DB_PASSWORD}" \
      --allocated-storage 20 --storage-type gp3 \
      --vpc-security-group-ids "${RDS_SG_ID}" \
      --db-name "${DB_NAME}" \
      --no-publicly-accessible \
      --backup-retention-period 7 \
      --region "${REGION}" >/dev/null
    echo "[provision] creating RDS ${DB_INSTANCE} (wait ~5 min)"
    aws rds wait db-instance-available --db-instance-identifier "${DB_INSTANCE}" --region "${REGION}"
    echo "[provision] RDS ${DB_INSTANCE} available"
  fi
  RDS_ENDPOINT="$(aws rds describe-db-instances --db-instance-identifier "${DB_INSTANCE}" \
    --query 'DBInstances[0].Endpoint.Address' --output text --region "${REGION}")"
  echo "[provision] RDS endpoint: ${RDS_ENDPOINT}:5432"
else
  echo "[provision] SKIP_RDS=1 — Postgres will run as a container on EC2"
  RDS_ENDPOINT="localhost:5432"
fi

# ---------------------------------------------------------------------------
# 6. EC2 + Elastic IP.
# ---------------------------------------------------------------------------
AMI="$(aws ssm get-parameters --names /aws/service/canonical/ubuntu/server/22.04/stable/current/amd64 \
  --query 'Parameters[0].Value' --output text --region "${REGION}")"
INSTANCE_ID="$(aws ec2 describe-instances --filters "Name=tag:Name,Values=${EC2_INSTANCE}" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text --region "${REGION}" 2>/dev/null || true)"
if [ -n "${INSTANCE_ID}" ] && [ "${INSTANCE_ID}" != "None" ]; then
  echo "[provision] EC2 ${EC2_INSTANCE} exists (${INSTANCE_ID})"
else
  INSTANCE_ID="$(aws ec2 run-instances \
    --image-id "${AMI}" --instance-type "${EC2_TYPE}" \
    --key-name "${KEY_NAME}" \
    --security-group-ids "${EC2_SG_ID}" \
    --iam-instance-profile "Name=homeai-ec2-profile" \
    --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=40,VolumeType=gp3}' \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${EC2_INSTANCE}}]" \
    --region "${REGION}" --query 'Instances[0].InstanceId' --output text)"
  echo "[provision] launched EC2 ${INSTANCE_ID} (${EC2_INSTANCE})"
  aws ec2 wait instance-running --instance-ids "${INSTANCE_ID}" --region "${REGION}"
fi

# Elastic IP (allocate if needed, associate to the instance).
EIP="$(aws ec2 describe-addresses --region "${REGION}" --query 'Addresses[?AssociationId==null].PublicIp' --output text | head -1 || true)"
if [ -z "${EIP}" ]; then
  EIP="$(aws ec2 allocate-address --domain vpc --region "${REGION}" --query PublicIp --output text)"
  echo "[provision] allocated EIP ${EIP}"
fi
aws ec2 associate-address --instance-id "${INSTANCE_ID}" --public-ip "${EIP}" --region "${REGION}" >/dev/null 2>&1 || true
echo "[provision] EC2 public IP: ${EIP}"

# ---------------------------------------------------------------------------
# 7. Budget alarm ($25).
# ---------------------------------------------------------------------------
ACCOUNT_ARN="arn:aws:iam::${ACCOUNT_ID}:root"
if aws budgets describe-budget --account-id "${ACCOUNT_ID}" --budget-name homeai-demo --region "${REGION}" >/dev/null 2>&1; then
  echo "[provision] budget homeai-demo exists"
else
  aws budgets create-budget --account-id "${ACCOUNT_ID}" --region "${REGION}" \
    --budget 'BudgetName=homeai-demo,BudgetLimit={Amount=25,Currency=USD},TimeUnit=MONTHLY,BudgetType=COST' \
    --notifications-with-subscribers 'NotificationType=ACTUAL,Threshold=80,ThresholdType=PERCENTAGE,Subscribers=[{SubscriptionType=EMAIL,Address='${BUDGET_EMAIL:-mohit@example.com}'}]' \
    >/dev/null 2>&1 || echo "[provision] budget creation skipped (needs email + permissions)"
fi

echo
echo "==========================================================================="
echo " Provisioning complete. Next steps:"
echo "   1. SSH to ${EIP} and install Docker + compose + awscli + postgresql-client."
echo "   2. Clone this repo, then: RDS_ENDPOINT=${RDS_ENDPOINT} TEAM=${TEAM} \\"
echo "        SITE_ADDRESS=<your-domain> make deploy-env > .env"
if [ -z "${SKIP_RDS:-}" ]; then
  echo "   3. Run init.sql once against RDS:"
  echo "        PGPASSWORD='${DB_PASSWORD}' psql -h ${RDS_ENDPOINT%:*} -U ${DB_MASTER_USER} -d ${DB_NAME} -f infra/db/init.sql"
fi
echo "   4. make deploy   (then make seed-c4 against RDS)"
echo "==========================================================================="
