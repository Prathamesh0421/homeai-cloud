# 08 — Final deliverables plan (integrated demo, scalability, final report)

The plan for everything after the component demos (11 Nov 2026). It turns the cloud design we submitted in
Deliverable #1 (**SRS v3 §7.3** and the **System Design Document (D1) §3**, both in `docs/deliverables/`) into
tasks, owners and acceptance checks. `06` §6 lists the headline items; this file is the detail.
**Read it before picking up any final-project task.**

Agreed 21 Nov 2026 (scope decision, see §2). Owners marked *(proposed)* are confirmed at the next team sync.

## 1. Deliverables and dates
| Deliverable | What | Date | Who |
|---|---|---|---|
| **D4 — Integrated demo / final presentation** | Group scenario E2E-1 live on AWS, scalability shown live, slides | **Wed 2 Dec 2026** | team |
| **D5 — Final package** | IEEE-format report (updates D1/D2 where the build changed), code, videos, `docs/RESULTS.md` | **Fri 11 Dec 2026** (course update; SRS §8 said 16 Dec) | team |

**Everything in Tier 1 and Tier 2 (§4–5) is built, deployed and measured before the 2 Dec presentation**, so
the live demo shows the scaled layout on AWS. The time after 2 Dec is only for the final package: writing the
report from the evidence already collected, fixing what the presentation feedback asks for, and tearing down AWS
after grading. No new infrastructure work is planned after the freeze.

Working dates: code complete and measured by **Sun 29 Nov** (freeze), rehearse **30 Nov – 1 Dec**, present
**2 Dec**, final package by **11 Dec**. Thanksgiving is Thu 26 Nov.

## 2. What the submitted design promises, and the scope we build
SRS v3 objective 6: *"Run on Amazon EC2, with a documented design for load balancing, scalability and
multi-tenancy."* SRS §7.3 and D1 §3.1 describe the production layout and say the demo may run on one EC2 with a
reverse proxy *"in place of the load balancer; the application is stateless, so moving to the load-balanced
layout changes instance counts and not code."* The team decided (21 Nov) to **prove that claim and deploy the
load-balanced, auto-scaled layout on AWS**, and to document the rest of D1 as the production target:

| Tier | Scope | Status |
|---|---|---|
| **1 — Horizontal scaling (built)** | Every service runs as N copies behind a load balancer on one host; no per-copy state; measured 1 vs 2 copies | to build: §4 (S-tasks) |
| **2 — AWS load balancing and auto scaling (built)** | ALB, Auto Scaling groups, HTTPS, CloudWatch, MongoDB off the host, images in a registry, as code | to build: §5 (A-tasks) |
| **3 — Production target (documented only)** | SQS hand-offs, Redis/ElastiCache, WebSockets, Multi-AZ RDS + read replica, NAT gateways, bastion, KMS, Glacier, Edge Hub, YOLOv8n video, SMS/escalation | report §7 explains why and how it would be added |

Tier 3 is not built because it changes the agreed contracts (`02` §4: REST and Mongo hand-offs, not SQS) in all
four components, or adds ~$150–300/month of AWS cost, and cannot be finished by 2 Dec.

### 2.1 D1 element → what we deploy
| D1 element (§3.1 table) | Deployed for D4 | Task |
|---|---|---|
| Route 53 + ACM, TLS 1.2+ at the ALB | ACM certificate on a team domain; HTTP→HTTPS redirect | A-6 |
| Application Load Balancer, path routing, `/health` checks | ALB → API target group (Caddy routes paths on each instance) | A-5 |
| API tier: EC2 Auto Scaling, t3.medium, min 2 / max 6, CPU 60 % | API ASG, min 1 / max 3 for cost (raise to 2 for the demo), CPU 60 % | A-7 |
| AI worker tier: Auto Scaling, c6i.xlarge, backlog-based | Worker ASG t3.medium (YAMNet only), min 1 / max 2, backlog metric (fallback CPU) | A-7, S-7 |
| RDS PostgreSQL (Multi-AZ + read replica) | Existing RDS db.t4g.micro, single-AZ (Tier 3: Multi-AZ, replica) | — |
| MongoDB Atlas replica set | MongoDB Atlas M0 (3-node replica set, free tier) | A-2 |
| ElastiCache Redis | not built (Tier 3); shared state lives in PostgreSQL instead (S-5) | — |
| S3 media bucket | existing bucket, shared by all instances | — |
| SQS queues + DLQs | not built (Tier 3); hand-offs stay REST + Mongo claims (`02` §4) | — |
| SNS / SES | SNS email (existing) | — |
| NAT gateway, bastion | not built (Tier 3); instances in public subnets, SG-restricted, SSH from team IPs | — |
| CloudWatch, Secrets Manager, ECR | CloudWatch logs + alarms; Secrets Manager (existing); ECR images | A-3, A-8 |

## 3. Rules for every final-project task
- Same rules as `AGENTS.md`: feature branch + PR, the owner of the touched folder reviews, CI green.
- **Nothing is created in AWS except by Mohit** (AWS lead; other members' IAM users are view-only). Others
  write the infrastructure code and the runbook; Mohit reviews and applies it.
- Infrastructure code lives in `infra/aws/` (Terraform, see A-1). No secrets or state files in git.
- **The repo is public**: rotate the service-client secrets and demo passwords before the ALB goes live (A-0).
- Every scalability claim in the report must point at evidence: a test, a measurement in `docs/RESULTS.md`, or a
  screenshot of the AWS console.

## 4. Tier 1 — horizontal scaling (S-tasks)
Goal: `docker compose ... up --scale c1-iot=2 --scale c2-alerts=2 --scale c3-data=2 --scale c3-worker=2
--scale c4-dashboard=2` works on one host, and every request still succeeds when one copy is stopped.

Audit (21 Nov): JWT on every request, all data in RDS/Mongo/S3; C1 ConnectivityMonitor and C2 jobs already take
a Postgres advisory lock; C3 workers claim clips atomically. Blocking items are S-1…S-6.

| ID | Task | Owner | Files | Done when |
|---|---|---|---|---|
| S-1 | Compose scale override: no fixed host ports for the app services, `--scale` safe; the dev file keeps its ports for Vite | Renuka *(proposed)* | `infra/docker-compose.scale.yml`, `03` §5 | `up --scale <svc>=2` starts two healthy copies of every service |
| S-2 | Caddy as the load balancer on each host: `dynamic a <service> <port>` upstreams (Docker DNS, `refresh 5s`), `lb_policy least_conn`, passive health checks (`fail_duration`, `max_fails`, `unhealthy_status 5xx`), `lb_try_duration` retries. Active health checks do not run for dynamic upstreams (Caddy docs) | Renuka *(proposed)* | `infra/caddy/Caddyfile` | requests spread over both copies (logs); stopping one copy gives no client errors after the retry window |
| S-3 | Migrations safe with N copies: each service's `alembic/env.py` takes `pg_advisory_lock(<per-service key>)` before `upgrade` (every copy runs `RUN_MIGRATIONS=1` on start) | each owner in their service | `services/cX_*/alembic/env.py` | 2 copies of a fresh service start with no migration error |
| S-4 | Scheduled jobs run once: C3 scheduler (backup, integrity, activity rollup) takes a Postgres advisory lock per run like C1/C2 (the `C3_SCHEDULER_ENABLED=false` flag cannot differ between `--scale` copies) | Renuka | `services/c3_data/app/scheduler.py` | with 2 copies each nightly job writes one result |
| S-5 | Shared rate limits: C2 public alert view (60/min/IP) and C3 records limiter count in PostgreSQL (fixed-window counter table, upsert) instead of process memory; the client IP must survive Caddy and the ALB (`X-Forwarded-For`, trusted proxies) | Prathamesh (C2), Renuka (C3) | `app/services/rate_limit.py`, a migration each | the limit holds across 2 copies (test with two app instances) |
| S-6 | Per-copy caches stay correct: C3 model cache reloads when another copy activates a model; C2 caches (HMAC key 5 min, C1 playback URLs) tolerate copies; C4 JWKS/revocation cache window documented | each owner | — | activation on copy A is used by copy B / every worker within the documented window |
| S-7 | Perf and scale scripts (`05` §7): `scripts/perf/clip_to_alert.py` (stage timings) and `scripts/perf/api_load.py` (concurrent `GET /alerts`, `POST /alerts/evaluate`, `GET /dashboard/summary`); C3 publishes the queued-clip backlog as a CloudWatch metric for A-7 | Renuka + Prathamesh | `scripts/perf/`, `docs/RESULTS.md` | p50/p95 tables for 1 vs 2 copies and 1 vs 2 workers |
| S-8 | Failover drill: stop one copy of each service under load | all | `docs/RESULTS.md` | error rate and recovery time recorded |

## 5. Tier 2 — AWS load balancing and auto scaling (A-tasks)
Layout: default VPC, two AZs, public subnets. ALB (HTTPS) → **API ASG** instances, each running Caddy + C1/C2/
C3-data/C4 from the same images (D1: "every instance runs the same image"). **Worker ASG** instances run only
`c3-worker`. All instances share RDS, MongoDB Atlas, S3, SNS and Secrets Manager. TLS ends at the ALB; Caddy
listens on :80 (`SITE_ADDRESS=:80`) and trusts the ALB for `X-Forwarded-For`.

| ID | Task | Owner | Done when |
|---|---|---|---|
| A-0 | Rotate secrets exposed by the public repo: `homeai/service-clients` + `c4.service_clients` hashes, demo passwords; `DEMO_MODE` only for the demo | Mohit | old dev secrets no longer mint tokens on AWS |
| A-1 | `infra/aws/terraform/` skeleton: provider, variables, outputs; local state (gitignored); `README` with plan/apply/destroy | Prathamesh *(proposed)*, Mohit reviews | `terraform validate` + `plan` clean |
| A-2 | MongoDB Atlas M0 (us-west-2): users per component (same roles as `infra/mongo` init), IP access list = instance IPs / NAT-less public IPs; move data with `mongodump`/`mongorestore` (C3 backup job); `MONGO_URL_*` from Secrets Manager | Mohit + Renuka | all services and workers use Atlas; the EC2-local Mongo is retired |
| A-3 | Images in ECR, one repository per service; GitHub Actions builds and pushes on merge to `main` (OIDC role, no static keys); instances pull instead of building (the C3 TensorFlow image is too slow to build at boot). Workflow: `.github/workflows/ecr-push.yml` (after green CI on `main`, or by hand; tags `:main` + `:sha-<commit>`; needs repo variable `AWS_ROLE_ARN`) | Prathamesh (CI owner) + Mohit (OIDC role) | a new instance starts from ECR images in < 5 min |
| A-4 | Launch templates + user data: install Docker, read `.env` values from Secrets Manager (instance role), pull images, `compose up` (API profile or worker profile); CloudWatch agent | Mohit *(proposed)* | a fresh instance joins healthy without SSH |
| A-5 | ALB: internet-facing, 2 AZs, target group HTTP :80 with health check `/api/v1/health/c4` (15 s, D1), least outstanding requests, deregistration delay 30 s; SGs: ALB 80/443 from anywhere, instances 80 from the ALB SG only, 22 from team IPs, RDS 5432 from the instance SG | Mohit | ALB DNS name serves the SPA and all APIs |
| A-6 | HTTPS: domain (Route 53 or external DNS) + ACM certificate, 443 listener, 80 → 443 redirect; `PUBLIC_BASE_URL` = the https URL (C2 signed links) | Mohit | `https://<domain>` works; alert emails link to it |
| A-7 | Auto Scaling: API ASG min 1 / max 3, target tracking CPU 60 %; worker ASG min 1 / max 2 on the queued-clip metric from S-7 (fallback CPU 60 %); C3 schedulers run on one API instance only (S-4 lock) | Mohit + Renuka | scale-out observed under `api_load.py` / `device_sim.py` load and recorded |
| A-8 | CloudWatch: container logs (awslogs driver or agent) per service; alarms for ALB 5xx, unhealthy hosts, CPU; the $25 budget alarm from `06` §5 (create it if missing); one dashboard | Mohit | dashboard screenshot in the report |
| A-9 | Runbook `infra/aws/README.md`: apply, deploy a new version (rolling instance refresh), scale for the demo, stop to save cost, destroy after grading | Mohit + Prathamesh | another member can follow it |
| A-10 | Re-run I-tests, Playwright specs and E2E-1 against the ALB URL | all | green on the ALB URL |

Cost guard: run the ASGs at min 1 outside test sessions, scale to 2 only for measurements and the demo, stop
everything when idle, destroy after grading (`06` §6).

## 6. Integration, E2E and polish (unchanged scope, owners)
| Item | Owner | Status 21 Nov |
|---|---|---|
| I-1 C1 → C3 | Ekant + Renuka | to automate in `tests/integration/` |
| I-2, I-3 C3/C4 → C2 | Prathamesh | done (`tests/integration/test_c2_detections.py`, green on EC2) |
| I-4 C2 → C1 clip | Prathamesh + Ekant | to do |
| I-5 dashboards | Mohit | to do |
| I-6 tenant isolation | all | to do |
| I-7 revocation | Mohit | to do |
| I-8 worker scale | Renuka | to do (with S-7) |
| E2E-1 test + `web/e2e/e2e-intrusion.spec.ts` | all (C4 leads the UI spec) | to do |
| Playwright `c1-feed-setup`, `c3-model-activate`, `c4-login-settings` | Ekant, Renuka, Mohit | `c1-feed-setup` done (C1-14); others to do (`c2-alert-lifecycle` done) |
| Accessibility pass (keyboard-only) per page | each owner | C1 pages done (focus into/out of forms, dialog focus trap, sortable headers, labelled Play); others to do |
| README: architecture, setup, demo accounts, dataset credits (ESC-50, YAMNet/AudioSet) | Mohit | partly done |
| Backups: restore drill on AWS | Renuka | to do |

New integration tests follow the pattern in `tests/integration/` (gateway only, real tokens, restore what they
change); new Playwright specs follow `web/e2e/` (`npm run e2e`, `E2E_BASE_URL`).

## 7. Final report (D5)
- Each owner updates their D2 chapter where the build changed, from `docs/CHANGELOG.md` and their plan's
  stand-in table. C2's known list: label checked before service; room > house > tenant precedence; clip URL not
  in `GET /alerts/{id}` (browser asks C1); evaluate reachable through the gateway (token only); retries
  effectively +1/+2 min; per-copy limits replaced by S-5.
- **Design vs deployed** section (team): the table in §2.1, why Tier 3 is not built, and what adding each Tier 3
  element would change (e.g. SQS: C1/C3/C2 hand-offs become queue consumers, contracts `02` §4 change).
- **Scalability evidence** (team): `docs/RESULTS.md` tables (S-7, S-8, A-7), AWS console screenshots (ALB
  targets, ASG activity, CloudWatch dashboard), and the multi-tenancy checks (I-6).

## 8. Timeline (proposed)
| Dates | Work |
|---|---|
| Sat 21 – Tue 24 Nov | S-1…S-6 PRs; A-0 secret rotation; A-1 Terraform skeleton; A-3 ECR pipeline |
| Tue 24 – Thu 26 Nov | A-2 Atlas move; A-4/A-5/A-6 applied; S-7 scripts |
| Fri 27 – Sat 28 Nov | A-7/A-8 on AWS; measurements (S-7, S-8, I-8) into `docs/RESULTS.md`; A-10 re-runs; E2E-1 |
| Sun 29 Nov | Freeze; slides with the scalability evidence |
| Mon 30 Nov – Tue 1 Dec | Two full rehearsals on the ALB URL; fallback: single-EC2 stack + recorded video |
| Wed 2 Dec | Present (D4), with the scaled AWS layout live |
| Thu 3 – Thu 10 Dec | Final report (§7): D2 chapter updates, design vs deployed, scalability evidence; feedback fixes |
| Fri 11 Dec | Final package (D5) submitted; tear down AWS after grading |

## 9. Picking up a task (members and AI assistants)
1. Read `AGENTS.md`, this file, and the plan of the component you touch.
2. Take the next open task with your name (or *proposed* with your name, after the team sync), on a branch
   `p0/<task-id>-<topic>` or `cX/<task-id>-<topic>`.
3. Shared files (`infra/`, `libs/`, `web/src/shared`, another component): PR reviewed by that owner.
4. Record the evidence named in "Done when" (test, `docs/RESULTS.md` row, or screenshot) in the PR description.
