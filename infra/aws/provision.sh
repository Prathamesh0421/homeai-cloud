#!/usr/bin/env bash
# HomeAI Cloud — one-time AWS provisioning for the demo (C4-16).
# Owner: Mohit. Source of truth: docs/03_REPO_AND_INFRA.md section 8,
# docs/07_DEMO_NOV_11.md section 5.
#
# Creates: S3 bucket, RDS instance, Secrets Manager secrets, IAM role + instance
# profile, EC2 + Elastic IP, and the security groups. Idempotent — safe to re-run
# after a partial failure.
#
#   TEAM=cmpe281 REGION=us-west-2 KEY_NAME=mohit-demo \
#     BUDGET_EMAIL=you@example.com \
#     infra/aws/provision.sh
#
# Required: TEAM, KEY_NAME
# Optional: REGION, DB_INSTANCE, EC2_INSTANCE, EC2_TYPE, DB_TYPE, DB_PASSWORD,
#           DB_BACKUP_DAYS (default 1 for free tier), SKIP_RDS=1

set -euo pipefail

REGION="${REGION:-us-west-2}"
TEAM="${TEAM:?TEAM is required (e.g. cmpe281)}"
KEY_NAME="${KEY_NAME:?KEY_NAME is required (an existing EC2 key pair)}"
DB_INSTANCE="${DB_INSTANCE:-homeai-db}"
EC2_INSTANCE="${EC2_INSTANCE:-homeai-ec2}"
# Free Tier only allows micro instances (t2.micro / t3.micro / t4g.micro).
# For the demo with TensorFlow (C3), override: EC2_TYPE=t3.medium (paid, ~$0.04/hr).
EC2_TYPE="${EC2_TYPE:-t3.micro}"
# Free-tier friendly defaults
DB_TYPE="${DB_TYPE:-db.t3.micro}"
DB_STORAGE_TYPE="${DB_STORAGE_TYPE:-gp2}"
DB_BACKUP_DAYS="${DB_BACKUP_DAYS:-1}"
DB_NAME="${DB_NAME:-homeai}"
DB_MASTER_USER="${DB_MASTER_USER:-postgres}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text --region "${REGION}")"
BUCKET="homeai-${TEAM}-${ACCOUNT_ID}"
echo "[provision] account=${ACCOUNT_ID} region=${REGION} bucket=${BUCKET}"

# RDS forbids '/', '@', '"', and space in the master password. Base64 is unsafe.
# Generate alphanumeric-only passwords (letters + digits).
rand_password() {
  local n="${1:-32}"
  # LC_ALL=C so tr only sees ASCII; openssl hex has no forbidden RDS chars.
  openssl rand -hex "$(( (n + 1) / 2 ))" | cut -c1-"${n}"
}

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

read_secret() {
  aws secretsmanager get-secret-value --secret-id "$1" --query SecretString --output text --region "${REGION}"
}

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
  echo "[provision] created bucket ${BUCKET}"
fi
aws s3api put-public-access-block --bucket "${BUCKET}" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true \
  --region "${REGION}"
aws s3api put-bucket-encryption --bucket "${BUCKET}" --region "${REGION}" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-lifecycle-configuration --bucket "${BUCKET}" --region "${REGION}" \
  --lifecycle-configuration file://infra/aws/s3-lifecycle.json
echo "[provision] bucket ${BUCKET} encryption + public-access block + lifecycle applied"

# ---------------------------------------------------------------------------
# 2. Security groups (idempotent create + rules).
# ---------------------------------------------------------------------------
EC2_SG_ID="$(aws ec2 describe-security-groups --group-names homeai-ec2 \
  --query 'SecurityGroups[0].GroupId' --output text --region "${REGION}" 2>/dev/null || true)"
if [ -z "${EC2_SG_ID}" ] || [ "${EC2_SG_ID}" = "None" ]; then
  EC2_SG_ID="$(aws ec2 create-security-group --group-name homeai-ec2 \
    --description "HomeAI EC2 host" --region "${REGION}" --query GroupId --output text)"
  echo "[provision] created SG homeai-ec2 (${EC2_SG_ID})"
else
  echo "[provision] SG homeai-ec2 exists (${EC2_SG_ID})"
fi
aws ec2 authorize-security-group-ingress --group-id "${EC2_SG_ID}" --region "${REGION}" \
  --ip-permissions IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges='[{CidrIp=0.0.0.0/0}]' \
                  IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges='[{CidrIp=0.0.0.0/0}]' \
                  IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges='[{CidrIp=0.0.0.0/0}]' \
  >/dev/null 2>&1 || true

RDS_SG_ID="$(aws ec2 describe-security-groups --group-names homeai-rds \
  --query 'SecurityGroups[0].GroupId' --output text --region "${REGION}" 2>/dev/null || true)"
if [ -z "${RDS_SG_ID}" ] || [ "${RDS_SG_ID}" = "None" ]; then
  RDS_SG_ID="$(aws ec2 create-security-group --group-name homeai-rds \
    --description "HomeAI RDS" --region "${REGION}" --query GroupId --output text)"
  echo "[provision] created SG homeai-rds (${RDS_SG_ID})"
else
  echo "[provision] SG homeai-rds exists (${RDS_SG_ID})"
fi
aws ec2 authorize-security-group-ingress --group-id "${RDS_SG_ID}" --region "${REGION}" \
  --ip-permissions "IpProtocol=tcp,FromPort=5432,ToPort=5432,UserIdGroupPairs=[{GroupId=${EC2_SG_ID}}]" \
  >/dev/null 2>&1 || true
echo "[provision] RDS SG allows 5432 from homeai-ec2"

# ---------------------------------------------------------------------------
# 3. Secrets Manager.
# Reuse homeai/db/master if it already exists so retries keep one password.
# ---------------------------------------------------------------------------
if [ -n "${DB_PASSWORD:-}" ]; then
  : # caller supplied
elif aws secretsmanager describe-secret --secret-id homeai/db/master --region "${REGION}" >/dev/null 2>&1; then
  # Replace if the stored value has RDS-forbidden characters from an earlier run.
  EXISTING_PW="$(read_secret homeai/db/master)"
  # RDS rejects '/', '@', '"', and space in MasterUserPassword.
  if [[ "${EXISTING_PW}" == */* || "${EXISTING_PW}" == *@* || "${EXISTING_PW}" == *\"* || "${EXISTING_PW}" == *" "* ]]; then
    echo "[provision] replacing homeai/db/master (had characters RDS rejects)"
    DB_PASSWORD="$(rand_password 32)"
  else
    DB_PASSWORD="${EXISTING_PW}"
    echo "[provision] reusing existing homeai/db/master password"
  fi
else
  DB_PASSWORD="$(rand_password 32)"
fi

JWT_PEM="${JWT_PEM:-$(openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 2>/dev/null)}"
HMAC_KEY="$(openssl rand -base64 32)"

upsert_secret "homeai/db/master" "${DB_PASSWORD}"
upsert_secret "homeai/jwt-signing-key" "${JWT_PEM}"
upsert_secret "homeai/alert-view-hmac" "${HMAC_KEY}"
for role in c1_app c2_app c2_reader c3_app c3_reader c4_app c4_reader; do
  if aws secretsmanager describe-secret --secret-id "homeai/db/${role}" --region "${REGION}" >/dev/null 2>&1; then
    echo "[provision] secret homeai/db/${role} exists (keeping)"
  else
    upsert_secret "homeai/db/${role}" "$(rand_password 32)"
  fi
done
for role in c2_reader c4_app; do
  if aws secretsmanager describe-secret --secret-id "homeai/mongo/${role}" --region "${REGION}" >/dev/null 2>&1; then
    echo "[provision] secret homeai/mongo/${role} exists (keeping)"
  else
    upsert_secret "homeai/mongo/${role}" "$(rand_password 32)"
  fi
done
SERVICE_CLIENTS_JSON='{"c2-alerts":"dev-c2-secret","c3-data":"dev-c3-secret","c3-worker":"dev-c3-secret","c4-dashboard":"dev-c4-secret","device-uploader":"dev-device-secret"}'
upsert_secret "homeai/service-clients" "${SERVICE_CLIENTS_JSON}"

# ---------------------------------------------------------------------------
# 4. IAM role + instance profile (always refresh the inline policy).
# ---------------------------------------------------------------------------
POLICY_DOC="$(mktemp)"
sed -e "s|\${TEAM}|${TEAM}|g" \
    -e "s|\${ACCOUNT_ID}|${ACCOUNT_ID}|g" \
    -e "s|\${AWS_REGION}|${REGION}|g" \
    infra/aws/ec2-policy.json > "${POLICY_DOC}"

if aws iam get-role --role-name homeai-ec2-role >/dev/null 2>&1; then
  echo "[provision] IAM role homeai-ec2-role exists"
else
  aws iam create-role --role-name homeai-ec2-role \
    --assume-role-policy-document file://infra/aws/ec2-trust-policy.json >/dev/null
  echo "[provision] created IAM role homeai-ec2-role"
fi
aws iam put-role-policy --role-name homeai-ec2-role --policy-name homeai-ec2-policy \
  --policy-document "file://${POLICY_DOC}"
rm -f "${POLICY_DOC}"

if aws iam get-instance-profile --instance-profile-name homeai-ec2-profile >/dev/null 2>&1; then
  echo "[provision] instance profile homeai-ec2-profile exists"
else
  aws iam create-instance-profile --instance-profile-name homeai-ec2-profile >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name homeai-ec2-profile \
    --role-name homeai-ec2-role
  echo "[provision] created instance profile; waiting 15s for IAM propagation..."
  sleep 15
fi

# ---------------------------------------------------------------------------
# 5. RDS (skip with SKIP_RDS=1).
# ---------------------------------------------------------------------------
if [ -z "${SKIP_RDS:-}" ]; then
  if aws rds describe-db-instances --db-instance-identifier "${DB_INSTANCE}" --region "${REGION}" >/dev/null 2>&1; then
    echo "[provision] RDS ${DB_INSTANCE} exists"
  else
    echo "[provision] creating RDS ${DB_INSTANCE} (class=${DB_TYPE}, storage=${DB_STORAGE_TYPE}, backup=${DB_BACKUP_DAYS}d)..."
    # Prefer Postgres 16; fall back to 15 if 16 is unavailable in this account/region.
    ENGINE_VERSION="${DB_ENGINE_VERSION:-16}"
    set +e
    aws rds create-db-instance \
      --db-instance-identifier "${DB_INSTANCE}" \
      --db-instance-class "${DB_TYPE}" \
      --engine postgres --engine-version "${ENGINE_VERSION}" \
      --master-username "${DB_MASTER_USER}" --master-user-password "${DB_PASSWORD}" \
      --allocated-storage 20 --storage-type "${DB_STORAGE_TYPE}" \
      --vpc-security-group-ids "${RDS_SG_ID}" \
      --db-name "${DB_NAME}" \
      --no-publicly-accessible \
      --backup-retention-period "${DB_BACKUP_DAYS}" \
      --region "${REGION}" >/tmp/homeai-rds-create.log 2>&1
    RC=$?
    set -e
    if [ "${RC}" -ne 0 ]; then
      if grep -qi "Cannot find version 16\|InvalidParameterCombination\|engine version" /tmp/homeai-rds-create.log; then
        echo "[provision] Postgres 16 unavailable; retrying with 15..."
        aws rds create-db-instance \
          --db-instance-identifier "${DB_INSTANCE}" \
          --db-instance-class "${DB_TYPE}" \
          --engine postgres --engine-version 15 \
          --master-username "${DB_MASTER_USER}" --master-user-password "${DB_PASSWORD}" \
          --allocated-storage 20 --storage-type "${DB_STORAGE_TYPE}" \
          --vpc-security-group-ids "${RDS_SG_ID}" \
          --db-name "${DB_NAME}" \
          --no-publicly-accessible \
          --backup-retention-period "${DB_BACKUP_DAYS}" \
          --region "${REGION}" >/dev/null
      else
        cat /tmp/homeai-rds-create.log >&2
        exit "${RC}"
      fi
    fi
    echo "[provision] waiting for RDS (often 5–10 min)..."
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
AMI="$(aws ssm get-parameter \
  --name /aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2/ami-id \
  --query 'Parameter.Value' --output text --region "${REGION}")"
echo "[provision] Ubuntu AMI: ${AMI}"

INSTANCE_ID="$(aws ec2 describe-instances --region "${REGION}" \
  --filters "Name=tag:Name,Values=${EC2_INSTANCE}" \
            "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || true)"
if [ -n "${INSTANCE_ID}" ] && [ "${INSTANCE_ID}" != "None" ]; then
  echo "[provision] EC2 ${EC2_INSTANCE} exists (${INSTANCE_ID})"
else
  # IAM instance profiles can take a moment to become attachable.
  for attempt in 1 2 3; do
    set +e
    INSTANCE_ID="$(aws ec2 run-instances \
      --image-id "${AMI}" --instance-type "${EC2_TYPE}" \
      --key-name "${KEY_NAME}" \
      --security-group-ids "${EC2_SG_ID}" \
      --iam-instance-profile "Name=homeai-ec2-profile" \
      --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=40,VolumeType=gp3}' \
      --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${EC2_INSTANCE}}]" \
      --region "${REGION}" --query 'Instances[0].InstanceId' --output text 2>/tmp/homeai-ec2-run.log)"
    RC=$?
    set -e
    if [ "${RC}" -eq 0 ] && [ -n "${INSTANCE_ID}" ] && [ "${INSTANCE_ID}" != "None" ]; then
      break
    fi
    if grep -qi "InvalidInstanceProfile\|not found\|association" /tmp/homeai-ec2-run.log; then
      echo "[provision] IAM profile not ready (attempt ${attempt}); waiting 15s..."
      sleep 15
    else
      cat /tmp/homeai-ec2-run.log >&2
      exit 1
    fi
  done
  echo "[provision] launched EC2 ${INSTANCE_ID} (${EC2_INSTANCE})"
  aws ec2 wait instance-running --instance-ids "${INSTANCE_ID}" --region "${REGION}"
fi

# Prefer an EIP already on this instance; else any free VPC EIP; else allocate.
ALLOC_ID="$(aws ec2 describe-addresses --region "${REGION}" \
  --filters "Name=instance-id,Values=${INSTANCE_ID}" \
  --query 'Addresses[0].AllocationId' --output text 2>/dev/null || true)"
EIP="$(aws ec2 describe-addresses --region "${REGION}" \
  --filters "Name=instance-id,Values=${INSTANCE_ID}" \
  --query 'Addresses[0].PublicIp' --output text 2>/dev/null || true)"

if [ -z "${ALLOC_ID}" ] || [ "${ALLOC_ID}" = "None" ]; then
  ALLOC_ID="$(aws ec2 describe-addresses --region "${REGION}" \
    --query 'Addresses[?AssociationId==`null`].AllocationId | [0]' --output text 2>/dev/null || true)"
  EIP="$(aws ec2 describe-addresses --region "${REGION}" \
    --query 'Addresses[?AssociationId==`null`].PublicIp | [0]' --output text 2>/dev/null || true)"
fi

if [ -z "${ALLOC_ID}" ] || [ "${ALLOC_ID}" = "None" ]; then
  # Query fields separately — AWS text output of a struct is not stable field order.
  ALLOC_ID="$(aws ec2 allocate-address --domain vpc --region "${REGION}" \
    --query 'AllocationId' --output text)"
  EIP="$(aws ec2 describe-addresses --allocation-ids "${ALLOC_ID}" --region "${REGION}" \
    --query 'Addresses[0].PublicIp' --output text)"
  echo "[provision] allocated EIP ${EIP} (${ALLOC_ID})"
fi

aws ec2 associate-address \
  --instance-id "${INSTANCE_ID}" \
  --allocation-id "${ALLOC_ID}" \
  --region "${REGION}" >/dev/null
echo "[provision] EC2 public IP: ${EIP}"

# ---------------------------------------------------------------------------
# 7. Budget alarm ($25). Budgets API lives in us-east-1 only.
# ---------------------------------------------------------------------------
if aws budgets describe-budget --account-id "${ACCOUNT_ID}" --budget-name homeai-demo \
  --region us-east-1 >/dev/null 2>&1; then
  echo "[provision] budget homeai-demo exists"
else
  aws budgets create-budget --account-id "${ACCOUNT_ID}" --region us-east-1 \
    --budget "BudgetName=homeai-demo,BudgetLimit={Amount=25,Currency=USD},TimeUnit=MONTHLY,BudgetType=COST" \
    --notifications-with-subscribers \
    "Notification={NotificationType=ACTUAL,ComparisonOperator=GREATER_THAN,Threshold=80,ThresholdType=PERCENTAGE},Subscribers=[{SubscriptionType=EMAIL,Address=${BUDGET_EMAIL:-ops@example.com}}]" \
    >/dev/null 2>&1 || echo "[provision] budget creation skipped (optional; check Budgets in us-east-1 console)"
fi

echo
echo "==========================================================================="
echo " Provisioning complete. Save these values:"
echo "   EC2 public IP : ${EIP}"
echo "   RDS endpoint  : ${RDS_ENDPOINT}:5432"
echo "   S3 bucket     : ${BUCKET}"
echo
echo " Next on the EC2 host:"
echo "   ssh -i <your.pem> ubuntu@${EIP}"
echo "   # install docker/git/awscli, clone repo, then:"
echo "   RDS_ENDPOINT=${RDS_ENDPOINT}:5432 TEAM=${TEAM} \\"
echo "     SITE_ADDRESS=:80 PUBLIC_BASE_URL=http://${EIP} make deploy-env > .env"
if [ -z "${SKIP_RDS:-}" ]; then
  echo "   # init DB once (password is in Secrets Manager homeai/db/master):"
  echo "   PGPASSWORD=\$(aws secretsmanager get-secret-value --secret-id homeai/db/master --query SecretString --output text) \\"
  echo "     psql -h ${RDS_ENDPOINT} -U ${DB_MASTER_USER} -d ${DB_NAME} -f infra/db/init.sql"
fi
echo "   make deploy && make seed-c4 && infra/aws/smoke.sh"
echo "==========================================================================="
