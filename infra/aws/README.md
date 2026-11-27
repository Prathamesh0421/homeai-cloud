# AWS setup runbook

Two layouts live in this directory:

| Layout | When | Entry |
|---|---|---|
| **Legacy / fallback** — single EC2 + Caddy | Nov demos; rehearsal backup if Tier 2 is down | §1–7 below (`provision.sh`) |
| **Tier 2** — ALB + ASGs + ECR + ACM | Final presentation (2 Dec); `docs/08` A-tasks | [§ Tier 2](#tier-2--alb--asg--terraform-docs08) + `terraform/README.md` |

Nothing in AWS is created except by **Mohit** (AWS lead). Rotate secrets first:
[`ROTATE_SECRETS.md`](./ROTATE_SECRETS.md) (A-0).

---

# Legacy / fallback — single EC2 (C4-16)

One-time provisioning + first deploy for the 11 Nov demo. Source of truth:
`docs/03_REPO_AND_INFRA.md` §8 and `docs/07_DEMO_NOV_11.md` §5. Kept as the
**fallback** if the ALB stack is not ready for rehearsal (08 §8).

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

`render_env.sh` reads the account ID and the passwords from AWS and prints a `.env` in
which every service connects as its own role (`c2_app`, `c2_reader`, `c4_app`, never the
RDS master), Mongo is `mongo:27017` (the compose service), AWS_ENDPOINT_URL is unset (real
AWS), `NOTIFIER=sns`, `DEMO_MODE` from the environment (default `0`; set `DEMO_MODE=1` only for the live demo — see [`ROTATE_SECRETS.md`](./ROTATE_SECRETS.md)). Without RDS: `SKIP_RDS=1 TEAM=… make deploy-env > .env`
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

## Files in this directory (legacy)

| File | Purpose |
|---|---|
| `provision.sh` | One-time resource creation (S3, RDS, Secrets, IAM, EC2, budget). |
| `ec2-policy.json` | IAM policy for the EC2 instance role (least privilege). |
| `ec2-trust-policy.json` | Trust policy allowing EC2 to assume the role. |
| `s3-lifecycle.json` | S3 lifecycle rules (tenants → IA/Glacier, backups expire). |
| `render_env.sh` | Prints a production `.env` from the provisioned resources. |
| `set_passwords.sh` | Sets the database roles and Mongo users to their Secrets Manager passwords (run by `make deploy`). |
| `ROTATE_SECRETS.md` | A-0 checklist before the ALB is public. |
| `terraform/` | Tier 2 IaC (see below). |

---

# Tier 2 — ALB / ASG / Terraform (`docs/08`)

Scalable layout: internet-facing ALB (HTTPS) → **API ASG** (Caddy + C1/C2/C3-data/C4
on each instance) and a separate **Worker ASG** (`c3-worker` only). Instances pull
images from ECR; config from Secrets Manager; shared RDS / S3 / SNS from the Nov
`provision.sh` resources. Full module docs: [`terraform/README.md`](./terraform/README.md).

## Prerequisites (Tier 2)

- [ ] A-0 done ([`ROTATE_SECRETS.md`](./ROTATE_SECRETS.md)).
- [ ] Terraform ≥ 1.5 locally; Mohit AWS admin credentials.
- [ ] `team_ssh_cidrs`, `rds_security_group_id`, `rds_endpoint` known.
- [ ] Prefer ECR images pushed at least once (`terraform/examples/ecr-push.yml`) before
      expecting healthy ALB targets (user-data can `--build` as a slow fallback).
- [ ] Atlas (A-2) for Mongo when retiring the EC2-local `mongo` container — optional for
      the first ALB bring-up if API instances still run compose `mongo`.

## Apply

```bash
cd infra/aws/terraform
cp examples/terraform.tfvars.example terraform.tfvars   # edit; do not commit
terraform init
terraform plan -out=tfplan
# Costly — only Mohit, only when ready:
terraform apply tfplan
```

Safer first pass (ECR, IAM, ALB, ACM request; **no** ASG EC2):

```bash
terraform apply -var='enable_asg=false'
```

### Free TLS path (no paid domain) — current course default

DuckDNS cannot create the ACM DNS-validation CNAME, and a Route 53 / purchased
domain costs money. **Do not enable the HTTPS listener** unless you have a real
DNS name that can host that CNAME.

| Audience | URL | TLS |
|---|---|---|
| Users / SPA / signed alert links | `https://homeai.duckdns.org` → legacy EIP + Caddy Let’s Encrypt | Yes (free) |
| Scalability demo (ALB) | `http://$(terraform output -raw alb_dns_name)` once ASG targets are healthy | HTTP only |

Keep `enable_https_listener=false` (default). Set
`PUBLIC_BASE_URL=https://homeai.duckdns.org` on the legacy host via `make deploy-env`.
In the final report “design vs deployed” note: ACM-at-ALB is the production target;
demo uses free DuckDNS+Caddy TLS + HTTP ALB for load-balancing evidence.

### Optional: ACM HTTPS (costs a domain)

If you later own a DNS zone that supports CNAMEs, set `domain_name`, apply, publish
`terraform output acm_validation_records`, then:

```bash
terraform apply -var='enable_https_listener=true' -var='enable_acm_validation_wait=true'
```

## Rolling refresh (new image / user-data)

After CI pushes a new `:main` (or change `ecr_image_tag` + apply):

```bash
API_ASG=$(terraform output -raw api_asg_name)
WORKER_ASG=$(terraform output -raw worker_asg_name)

aws autoscaling start-instance-refresh \
  --auto-scaling-group-name "$API_ASG" \
  --preferences MinHealthyPercentage=50,InstanceWarmup=300 \
  --region us-west-2

aws autoscaling start-instance-refresh \
  --auto-scaling-group-name "$WORKER_ASG" \
  --preferences MinHealthyPercentage=0,InstanceWarmup=300 \
  --region us-west-2
```

Or bump the launch template by re-applying after a user-data change (`$Latest`).

## Scale for the demo

```bash
# API: show 2 copies behind the ALB (08 cost note: raise only for demo / measurements)
aws autoscaling set-desired-capacity --auto-scaling-group-name "$API_ASG" --desired-capacity 2
# Workers: optional second worker under device_sim / api_load
aws autoscaling set-desired-capacity --auto-scaling-group-name "$WORKER_ASG" --desired-capacity 2
```

Return to min cost after the session:

```bash
aws autoscaling set-desired-capacity --auto-scaling-group-name "$API_ASG" --desired-capacity 1
aws autoscaling set-desired-capacity --auto-scaling-group-name "$WORKER_ASG" --desired-capacity 1
```

## Stop to save cost (idle days)

```bash
# Scale to zero (keeps ALB + ASG objects; no EC2 burn)
aws autoscaling update-auto-scaling-group --auto-scaling-group-name "$API_ASG" \
  --min-size 0 --desired-capacity 0 --max-size 3
aws autoscaling update-auto-scaling-group --auto-scaling-group-name "$WORKER_ASG" \
  --min-size 0 --desired-capacity 0 --max-size 2

# Optional: stop legacy single-EC2 + RDS as in §7 above
```

Bring back: set min/desired to 1 (or `terraform apply` to restore coded defaults).

## Destroy after grading

```bash
cd infra/aws/terraform
terraform destroy
```

This removes ALB, ASGs, Tier-2 SGs/IAM/ECR/OIDC role, ACM cert, log groups. It does
**not** delete the Nov RDS, S3 bucket, or `homeai/*` secrets. Tear those down
separately only after backups/dumps are safe (and after the report is submitted).

## Fallback

If Tier 2 is unhealthy before a rehearsal: keep DuckDNS on the **legacy EIP**, use
§1–7 above, and show the recorded scale video / local `--scale` measurements from
`docs/RESULTS.md` (08 §8 Mon–Tue fallback).
