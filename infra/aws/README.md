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
  Postgres container fallback — `07` §3).
- **EC2** Ubuntu 22.04 `t3.large` + Elastic IP, with the IAM role attached.
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

`render_env.sh` reads the account ID and the passwords from AWS and prints a `.env` in
which every service connects as its own role (`c2_app`, `c2_reader`, `c4_app`, never the
RDS master), Mongo is `mongo:27017` (the compose service), AWS_ENDPOINT_URL is unset (real
AWS), `NOTIFIER=sns`, `DEMO_MODE=1`. Without RDS: `SKIP_RDS=1 TEAM=… make deploy-env > .env`
(Postgres is then the `postgres:5432` container).

## 4. Initialise the database (RDS only)

```bash
PGPASSWORD="$(aws secretsmanager get-secret-value --secret-id homeai/db/master \
  --query SecretString --output text)" \
  psql -h <rds-endpoint> -U postgres -d homeai -f infra/db/init.sql
```

`init.sql` works as the RDS master (not a superuser): it makes the master a member of the
`cX_app` roles before setting their default privileges. With `SKIP_RDS=1` the Postgres
container runs `init.sql` itself; skip this step.

## 5. Deploy the stack

```bash
RDS_ENDPOINT=<rds-endpoint>:5432 make deploy     # or: SKIP_RDS=1 make deploy
```

1. Starts the data layer (Mongo; Postgres too with `SKIP_RDS=1`).
2. Runs `set_passwords.sh`: sets every database role and Mongo user to its Secrets Manager
   password, the ones `.env` now holds (`init.sql`/`init.js` create them with the dev
   password). Safe to re-run.
3. Starts everything with the `gateway` (Caddy) and `c3` profiles, plus `c1` once
   `services/c1_iot` exists:
   `docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml --profile gateway --profile c3 up -d --build`.

Caddy publishes 80/443 and obtains a Let's Encrypt cert when `SITE_ADDRESS` is a real
domain. `make deploy-down` / `make deploy-logs` use the same profiles.

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
| `set_passwords.sh` | Sets the database roles and Mongo users to their Secrets Manager passwords (run by `make deploy`). |
