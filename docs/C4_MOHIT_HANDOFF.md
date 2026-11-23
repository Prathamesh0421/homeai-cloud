# C4 / AWS lead handoff — Mohit (23 Nov 2026)

Status against `docs/08_FINAL_DELIVERABLES.md` after the Nov 11 demo. **No paid
domain** — HTTPS for users stays on DuckDNS + Caddy LE; ALB is HTTP for the
scalability story (`infra/aws/README.md` Tier 2 free-TLS path).

Account: `547250341198` · Region: `us-west-2` · Domain (users): `homeai.duckdns.org`

---

## Done (Mohit-owned, not blocked)

| ID | What | Evidence |
|---|---|---|
| **S-3** | C4 Alembic `pg_advisory_lock(0x4334_0000_0001)` | `services/c4_dashboard/alembic/env.py` |
| **S-6** | 60s `/auth/revoked` cache in `homeai_common`; JWKS 10 min unchanged | `libs/homeai_common/homeai_common/auth.py`, unit tests, `docs/components/C4_DASHBOARD_AND_AUTH.md` |
| **I-5** | Dashboard integration test | `tests/integration/test_c4_dashboard.py` (needs seeded stack to run) |
| **I-7** | Revocation integration test | `tests/integration/test_c4_revocation.py` (needs stack + image rebuild so C1–C3 pick up common) |
| **C4-17** | Playwright login/settings | `web/e2e/c4-login-settings.spec.ts` (typecheck clean; run with `E2E_BASE_URL`) |
| **A-0** | Service-client + demo password rotation; `DEMO_MODE=0` on AWS | Secrets Manager new version; RDS hashes updated; verified 401/200 on EC2. Plaintext in **gitignored** `secrets/a0-rotated.env` only |
| **A-1** | Terraform skeleton | `infra/aws/terraform/` — `terraform validate` OK |
| **A-3** | ECR repos + GitHub OIDC + push role | Applied; role `arn:aws:iam::547250341198:role/homeai-prod-gha-ecr-push` |
| **A-4…A-6** | User-data templates, ALB, SGs, ACM *requested* | Applied with `enable_asg=false`, `enable_https_listener=false`. ALB: `homeai-prod-alb-665011090.us-west-2.elb.amazonaws.com` |
| **A-7/A-8** | ASG + CW alarms/log groups in TF | Code ready; ASG not enabled yet (no ECR images / cost). Alarms exist for ALB |
| **A-9** | Tier 2 runbook + A-0 checklist | `infra/aws/README.md`, `infra/aws/ROTATE_SECRETS.md` |
| **RESULTS** | Measurement stub | `docs/RESULTS.md` |
| **Prod hygiene** | `DEMO_MODE` default 0 | `infra/docker-compose.prod.yml`, `infra/aws/render_env.sh` |

C4 feature UI/API from the Nov demo (C4-01…C4-15 path) remains in place: auth, settings, dashboards, tenants/users, shell.

### Live AWS snapshot (23 Nov)

- Legacy EC2 `i-0f57a0eeb010bbbae` (EIP `44.226.166.194`) — started for A-0 verify; **stop when idle**
- RDS `homeai-db.cdsuyom6mpgo.us-west-2.rds.amazonaws.com` available
- Terraform state: **local** under `infra/aws/terraform/` (gitignored) on Mohit’s machine
- ACM cert for `homeai.duckdns.org` is **PENDING** — intentionally unused (no free DNS validation)

---

## Blocked / teammate / deferred (not claimed done)

| Item | Owner / why |
|---|---|
| **S-1 / S-2** | Renuka — scale compose + Caddy dynamic upstreams |
| **S-7 / I-8** | Renuka (+ Prathamesh) — perf scripts + worker backlog metric |
| **S-8 / A-10** | All — failover + I-tests/Playwright against ALB (needs healthy targets) |
| **A-2 Atlas** | Mohit + Renuka — Mongo off EC2 |
| **A-3 CI push** | Prathamesh landed `.github/workflows/ecr-push.yml` on main (#31). Still needs repo variable `AWS_ROLE_ARN` = `arn:aws:iam::547250341198:role/homeai-prod-gha-ecr-push` |
| **A-7 live ASG** | Mohit after ECR images exist — `terraform apply` with `enable_asg=true` |
| **A-6 ACM HTTPS** | Skipped — no paid domain; free path = DuckDNS+Caddy HTTPS + HTTP ALB |
| **E2E-1** `e2e-intrusion.spec.ts` | Team — C4 leads UI; not written yet |
| **I-6** | All — tenant isolation pass |
| **Rebuild images** | So C1–C3 pick up S-6 `homeai_common` before I-7 is meaningful in prod |

---

## How teammates use this

1. **Prathamesh:** OIDC role ARN above + `examples/ecr-push.yml` → push `:main` to ECR.
2. **Renuka:** Land S-1/S-2; coordinate Atlas (A-2).
3. **Mohit next:** After images exist → enable ASG → register targets → fill `docs/RESULTS.md` → A-10 on ALB HTTP URL; keep DuckDNS on legacy EIP for HTTPS users until cutover plan changes.
4. **Secrets:** Never commit `secrets/a0-rotated.env` or `terraform.tfvars`. Share new demo password out-of-band only.

---

## Design vs deployed (one-liner for the report)

Submitted design: TLS at ALB (ACM). Deployed for cost-free demo: TLS at Caddy on the single EC2 (Let’s Encrypt + DuckDNS); ALB HTTP for load-balancing / ASG evidence. Adding ACM requires a DNS zone that supports validation CNAMEs (paid domain or equivalent).
