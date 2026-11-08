# AWS setup runbook (C4-16)

One-time provisioning + first deploy for the 11 Nov demo. Source of truth:
`docs/03_REPO_AND_INFRA.md` §8 and `docs/07_DEMO_NOV_11.md` §5. Run this once as a
team on **Sun 8 Nov** (~2 hours).

## Prerequisites

- An AWS account in `us-west-2` with billing alerts enabled.
- An EC2 key pair named (e.g.) `mohit-demo` for SSH access.
- `aws` CLI configured with admin credentials on the machine that runs
  `provision.sh` (not the EC2 host itself).

## 1. Provision resources (once, from an admin machine)

```bash
TEAM=cmpe281 REGION=us-west-2 KEY_NAME=mohit-demo \
  BUDGET_EMAIL=your-email@example.com \
  infra/aws/provision.sh
```

This creates:

- **S3** bucket `homeai-cmpe281-<accountid>` (Block Public Access, SSE-S3, lifecycle).
- **Security groups** `homeai-ec2` (80/443/22) and `homeai-rds` (5432 from `homeai-ec2`).
- **Secrets Manager** secrets: `homeai/db/master`, `homeai/db/<role>` for each
  role, `homeai/mongo/<user>`, `homeai/jwt-signing-key`, `homeai/alert-view-hmac`,
  `homeai/service-clients`.
- **IAM** role `homeai-ec2-role` + instance profile using
  `infra/aws/ec2-policy.json` (S3, SNS incl. Unsubscribe/GetSubscriptionAttributes/ListTopics,
  Secrets Manager `homeai/*`).
- **RDS** PostgreSQL 16 `db.t4g.micro` (or skip with `SKIP_RDS=1` to use the
  Postgres container fallback — `07` §3). Free-tier accounts get
  `--backup-retention-period 1` (override with `DB_BACKUP_DAYS=7` if you leave free tier).
- **EC2** Ubuntu 22.04 + Elastic IP, with the IAM role attached. Default size is
  **`t3.micro`** (Free Tier). For the demo with C3/TensorFlow use
  `EC2_TYPE=t3.medium` or `t3.large` (paid). RDS defaults to `db.t3.micro` +
  `gp2` + 1-day backups for Free Tier.
- **Budget alarm** at $25/month.

Printed at the end: the EC2 public IP and RDS endpoint.

## 2. Bootstrap the EC2 host (SSH in once)

```bash
ssh -i <key> ubuntu@<EC2_PUBLIC_IP>
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git awscli postgresql-client
sudo usermod -aG docker $USER && newgrp docker
git clone <repo-url> ~/homeai-cloud && cd ~/homeai-cloud
```

## 3. Render the production `.env`

On the EC2 host, with the instance profile active (no static keys):

```bash
RDS_ENDPOINT=<rds-endpoint>:5432 TEAM=cmpe281 \
  SITE_ADDRESS=homeai.duckdns.org \
  PUBLIC_BASE_URL=https://homeai.duckdns.org \
  make deploy-env > .env
```

`render_env.sh` fetches the RDS master password and account ID from AWS and
prints a `.env` with `AWS_ENDPOINT_URL` empty (real AWS), `NOTIFIER=sns`,
`DEMO_MODE=1`.

## 4. Initialise the database (RDS only)

```bash
PGPASSWORD='<db-master-password>' psql -h <rds-endpoint> -U postgres -d homeai \
  -f infra/db/init.sql
```

(If `SKIP_RDS=1`, `make deploy` starts the Postgres container which runs
`init.sql` automatically.)

## 5. Deploy the stack

```bash
make deploy
```

Runs `docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml up -d --build`.
Caddy publishes 80/443 and obtains a Let's Encrypt cert when `SITE_ADDRESS`
is a real domain.

## 6. Seed + smoke test

```bash
# C4 seed against RDS (migrations run automatically on container start)
make seed-c4

# Smoke
curl -s http://localhost/api/v1/health/c4
# Login as ops
curl -s -X POST http://localhost/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"ops@homeai.test","password":"Demo!2026"}'
```

Then ask C2 to run their subscription sync and **confirm the demo contact
emails** (Sun 8, re-check Tue 10).

## 7. Cost control

- Stop EC2 and RDS when not demoing: `aws ec2 stop-instances`, `aws rds stop-db-instance`.
- RDS stays stopped up to 7 days; resume with `aws rds start-db-instance`.
- Tear everything down after grading.

## Files in this directory

| File | Purpose |
|---|---|
| `provision.sh` | One-time resource creation (S3, RDS, Secrets, IAM, EC2, budget). |
| `ec2-policy.json` | IAM policy for the EC2 instance role (least privilege). |
| `ec2-trust-policy.json` | Trust policy allowing EC2 to assume the role. |
| `s3-lifecycle.json` | S3 lifecycle rules (tenants → IA/Glacier, backups expire). |
| `render_env.sh` | Prints a production `.env` from the provisioned resources. |
