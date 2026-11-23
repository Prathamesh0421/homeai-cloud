# Tier 2 — Terraform (ALB / ASG / ECR / ACM)

Infrastructure-as-code for `docs/08_FINAL_DELIVERABLES.md` tasks **A-1, A-3…A-8**.
Mohit (AWS lead) reviews and is the only person who **applies** this in the course account.

**Do not apply blindly.** ALB + ASG EC2 instances cost money. Prefer `terraform plan` until
secrets are rotated (A-0) and ECR images exist.

## What this stack creates

| Resource | Notes |
|---|---|
| Security groups | ALB 80/443 world; instances 80←ALB, 22←`team_ssh_cidrs` |
| ALB + target group | HTTP :80, health `/api/v1/health/c4` @ 15s, least outstanding requests, drain 30s |
| ACM certificate | `var.domain_name` (default `homeai.duckdns.org`); DuckDNS TXT/CNAME **manual** |
| HTTPS listener | Gated by `enable_https_listener` (after ACM validates) |
| Launch templates + ASGs | API min1/max3 CPU 60%; worker min1/max2 CPU 60% fallback |
| IAM instance role | Secrets `homeai/*`, S3, SNS, ECR pull, CloudWatch |
| GitHub OIDC + role | ECR **push** for Actions (`github_actions_ecr_role_arn`) |
| ECR repos | `homeai/c1-iot`, `c2-alerts`, `c3-data`, `c3-worker`, `c4-dashboard`, `web` |
| CloudWatch | Log groups `/homeai/<env>/<svc>`; ALB 5xx + unhealthy-host alarms |

## What is reused from `provision.sh` (not destroyed)

| Existing | How Terraform sees it |
|---|---|
| RDS `homeai-db` | `rds_endpoint` + optional `rds_security_group_id` (adds 5432 from instance SG only) |
| S3 `homeai-<team>-<account>` | `s3_bucket_name` or derived name — IAM only |
| Secrets Manager `homeai/*` | Read by instance role + user-data; never recreated here |
| Single EC2 + EIP + `homeai-ec2-role` | **Legacy / fallback** — leave running until ALB cutover |
| $25 budget alarm | Still owned by `provision.sh` |

MongoDB Atlas (A-2) is created outside this module; put connection URLs into Secrets Manager
(or a single `homeai/runtime-env` blob) before relying on worker/API ASGs without local Mongo.

## Prerequisites

- Terraform ≥ 1.5, AWS credentials that can create ALB/ASG/IAM/ECR (Mohit admin).
- Existing Nov demo resources from `../provision.sh` (or know you are in an empty sandbox).
- A-0 secret rotation done before the ALB is public.
- At least one successful ECR push (sample workflow in `examples/ecr-push.yml`) before expecting
  healthy targets (user-data can `--build` as a slow fallback).

## Init / plan / apply / destroy

```bash
cd infra/aws/terraform
cp examples/terraform.tfvars.example terraform.tfvars   # edit; never commit real secrets
terraform init
terraform fmt -recursive
terraform validate
terraform plan -out=tfplan

# Only when ready (costs money):
terraform apply tfplan
```

Useful first apply (network + ECR + IAM, no ASG EC2 yet):

```bash
terraform apply -var='enable_asg=false'
```

Enable HTTPS after DuckDNS validation records from `acm_validation_records` are published:

```bash
terraform apply -var='enable_https_listener=true' -var='enable_acm_validation_wait=true'
```

Tear down Tier-2 only (leaves RDS/S3/Secrets/single-EC2 alone):

```bash
terraform destroy
```

State is **local** (`*.tfstate*`). Those files are gitignored. Do not commit them.

## Important variables

| Variable | Default | Purpose |
|---|---|---|
| `domain_name` | `homeai.duckdns.org` | ACM + PUBLIC_BASE_URL hint |
| `team_ssh_cidrs` | `[]` | SSH to instances; set your /32s before apply |
| `rds_security_group_id` | `""` | Existing `homeai-rds` SG id |
| `rds_endpoint` | `""` | Injected into user-data for `render_env.sh` |
| `github_org` / `github_repo` | repo defaults | OIDC trust for ECR push |
| `enable_asg` | `true` | Launch templates + ASGs |
| `enable_https_listener` | `false` | 443 + HTTP→HTTPS redirect |
| `ecr_image_tag` | `main` | Tag user-data pulls |
| `repo_clone_url` / `repo_ref` | public clone | Compose/Caddy files on the instance |

See `variables.tf` for the full list. Use `examples/terraform.tfvars.example` as a template —
**no passwords in tfvars**.

## User-data (A-4)

Templates: `templates/user_data_api.sh.tpl`, `templates/user_data_worker.sh.tpl`.

Both scripts:

1. Install Docker + Compose plugin + AWS CLI + CloudWatch agent (idempotent).
2. Clone the repo for compose files.
3. Load `.env` from `homeai/runtime-env` if present, else run `infra/aws/render_env.sh`.
4. `docker login` to ECR, pull tagged images, `compose up` API services vs `c3-worker`.

Documented secret keys are listed in the template headers. Prefer a single
`homeai/runtime-env` secret once Atlas URLs are known so every instance gets the same file.

## CI hook (A-3)

Output `github_actions_ecr_role_arn` → GitHub Actions `role-to-assume`.

Sample workflow (does **not** change the green `ci.yml` path):  
`examples/ecr-push.yml` — Prathamesh can merge into `.github/workflows/` behind
`workflow_dispatch` / environment `aws`. Existing `build-images` keeps `push: false`.

## Cost guard

- Keep ASG desired = 1 outside measurements; raise API desired to 2 only for the demo.
- Stop ASG instances when idle: set min/desired to 0 (or `terraform apply -var='enable_asg=false'` after draining).
- `terraform destroy` after grading; keep `provision.sh` teardown separate if you still need RDS dumps.
