# 03 — Repository, shared library, infrastructure and deployment

Owner of this file's setup work: **Mohit (C4)** leads Phase 0; everyone reviews. Phase 0 tasks are
P0-1 … P0-12 at the end of this file.

---
## 1. Monorepo layout
```
homeai-cloud/
├── AGENTS.md                     # rules for AI assistants (copy also to CLAUDE.md if needed)
├── README.md                     # quick start
├── Makefile                      # dev commands (section 6)
├── pyproject.toml                # ruff config shared by all Python code
├── .env.example                  # every variable, no secrets
├── docs/                         # this plan
├── libs/
│   └── homeai_common/            # shared Python package (section 2), installed in every service image
│       ├── pyproject.toml
│       └── homeai_common/{__init__,config,auth,errors,pagination,logging,db,mongo,service_client,s3,health,testing}.py
├── services/
│   ├── c1_iot/                   # C1 FastAPI app
│   ├── c2_alerts/                # C2 FastAPI app
│   ├── c3_data/                  # C3 FastAPI app + worker entrypoint
│   └── c4_dashboard/             # C4 FastAPI app
│       (each service has the same internal layout — section 1.1)
├── web/                          # React SPA (see 04_FRONTEND.md)
├── infra/
│   ├── docker-compose.yml        # local dev stack
│   ├── docker-compose.prod.yml   # EC2 overrides (no Postgres/LocalStack, uses RDS + real AWS)
│   ├── caddy/Caddyfile           # gateway + SPA (local and prod variants)
│   ├── db/init.sql               # schemas, roles, grants
│   ├── mongo/init.js             # users and roles
│   ├── localstack/init-aws.sh    # bucket, secrets for local dev
│   └── aws/                      # setup scripts + IAM policy JSON (section 8)
├── scripts/
│   ├── seed.py                   # idempotent demo seed through each service's API + direct SQL where needed
│   ├── mint_token.py             # dev only: prints a JWT for a seeded user or service client
│   ├── device_sim.py             # uploads clips for a feed on an interval (C1 demo)
│   ├── fetch_demo_clips.sh       # downloads/creates demo audio clips into ./demo_clips
│   └── demo/                     # per-member demo helper scripts
└── .github/workflows/ci.yml
```

### 1.1 Layout inside every service (example C2)
```
services/c2_alerts/
├── Dockerfile
├── pyproject.toml                # depends on homeai-common (path dependency)
├── alembic.ini
├── alembic/versions/0001_initial.py
├── app/
│   ├── main.py                   # create_app(): routers, middleware, exception handlers, scheduler
│   ├── settings.py               # pydantic-settings, env prefix C2_
│   ├── api/                      # routers only (alerts.py, rules.py, evaluate.py, alert_view.py, health.py)
│   ├── schemas/                  # Pydantic request/response models
│   ├── services/                 # business logic (rule_engine.py, lifecycle.py, notification.py, signed_link.py)
│   ├── repositories/             # SQLAlchemy / PyMongo access
│   ├── gateways/                 # other components and AWS (detection_gateway.py, sns_gateway.py, ...)
│   ├── models/                   # SQLAlchemy ORM classes
│   └── jobs/                     # APScheduler jobs
└── tests/
    ├── conftest.py               # app client, db fixtures, token fixtures
    ├── unit/                     # pure logic (no DB)
    └── api/                      # endpoint tests against test DB
```

---
## 2. Shared library `homeai_common` (built in Phase 0, owned by C4, reviewed by all)
| Module | Provides |
|---|---|
| `config` | `BaseServiceSettings` (pydantic-settings): `ENV`, `DATABASE_URL`, `DATABASE_READER_URL`, `MONGO_URL`, `AWS_REGION`, `AWS_ENDPOINT_URL` (LocalStack), `S3_BUCKET`, `JWKS_URL`, `C4_BASE_URL`, `SERVICE_CLIENT_ID`, `SERVICE_CLIENT_SECRET`, `PUBLIC_BASE_URL`, `GIT_SHA` |
| `errors` | `ApiError(status, code, message, details)`; FastAPI handlers mapping `ApiError`, `RequestValidationError`, `HTTPException` and unexpected exceptions to the error envelope (section 1 of contracts) |
| `pagination` | `PageParams` dependency (`page`, `page_size`), `page_response(items, total, params)` |
| `auth` | `JwksCache`, `verify_token()`, `Principal`, dependencies `current_principal`, `require_roles(...)`, `require_scope(...)`, helpers `assert_house(...)`, `tenant_filter(...)` |
| `service_client` | `ServiceTokenProvider` (calls C4 `/auth/service-token`, caches) and `ServiceHttpClient` (httpx with bearer, timeouts 5 s, retries on 502/503/504 with 2/4/8 s backoff) |
| `logging` | JSON logging setup; `RequestIdMiddleware` |
| `db` | `make_engine(url)`, `session_scope()` context manager, `get_session` dependency |
| `mongo` | `get_mongo_db()` (PyMongo client singleton, `uuidRepresentation="standard"`) |
| `s3` | `s3_client()` (respects `AWS_ENDPOINT_URL`), `presign_get(bucket, key, ttl)` |
| `health` | `health_router(service_name, checks)` |
| `testing` | `make_test_keys()`, `mint_user_token(...)`, `mint_service_token(...)` for tests (uses a test RSA key and a fake JWKS) |

Acceptance for the library: unit tests for token verification (valid, expired, wrong aud, unknown kid,
revoked jti), error envelope mapping, pagination math; 90% line coverage.

---
## 3. Docker images
- Base for C1, C2, C4: `python:3.11-slim`; install `libs/homeai_common` then the service; run
  `uvicorn app.main:app --host 0.0.0.0 --port 80xx --proxy-headers`.
- C3: `python:3.11-slim` + `apt-get install -y ffmpeg libsndfile1`; `tensorflow-cpu` and `tensorflow-hub`.
  The YAMNet model is downloaded at build time (`scripts/download_yamnet.py` inside the image) into
  `/models/yamnet/1` so the container starts offline. Same image runs two commands: API (`uvicorn`) and
  worker (`python -m app.worker`).
- Web: `node:20` build stage → static files copied into the Caddy image (`infra/caddy/Dockerfile`).
- Each service image runs `alembic upgrade head` on start when `RUN_MIGRATIONS=1` (only one replica runs).

---
## 4. Docker Compose (local) — `infra/docker-compose.yml`
Services:
| Service | Image | Ports | Notes |
|---|---|---|---|
| `postgres` | `postgres:16` | 5432 | mounts `infra/db/init.sql` |
| `mongo` | `mongo:7` | 27017 | mounts `infra/mongo/init.js`; volume `mongo-data` |
| `localstack` | `localstack/localstack:3` | 4566 | `SERVICES=s3,sns,secretsmanager`; runs `infra/localstack/init-aws.sh` |
| `c4-dashboard` | build | 8004 | starts first; others depend on it (JWKS) |
| `c1-iot` | build | 8001 | |
| `c2-alerts` | build | 8002 | `NOTIFIER=log` locally (prints emails); `NOTIFIER=sns` on AWS |
| `c3-data` | build | 8003 | |
| `c3-worker` | same image as c3-data | — | `command: python -m app.worker` |
| `caddy` | build (`infra/caddy`) | 8080→80 | gateway + SPA build; for hot reload use `npm run dev` on 5173 with Vite proxy |
Health checks on every service (`/api/v1/health/<cx>`); `depends_on: condition: service_healthy`.

`docker-compose.prod.yml` removes `postgres` and `localstack`, sets `DATABASE_URL` to RDS, removes
`AWS_ENDPOINT_URL`, sets `NOTIFIER=sns`, exposes Caddy on 80/443 with automatic HTTPS for `$DOMAIN`.

### 4.1 Caddyfile (gateway)
```
{$SITE_ADDRESS:":80"} {
  encode gzip
  @c4houses path_regexp c4houses ^/api/v1/(houses/[^/]+/(settings|emergency-contacts)|emergency-contacts)
  handle @c4houses { reverse_proxy c4-dashboard:8004 }
  @c4 path /api/v1/auth/* /api/v1/dashboard/* /api/v1/tenants* /api/v1/users/* /.well-known/jwks.json /api/v1/docs/c4* /api/v1/health/c4
  handle @c4 { reverse_proxy c4-dashboard:8004 }
  @c1 path /api/v1/houses* /api/v1/rooms* /api/v1/feeds* /api/v1/ingest/* /api/v1/clips* /api/v1/docs/c1* /api/v1/health/c1
  handle @c1 { reverse_proxy c1-iot:8001 }
  @c2 path /api/v1/alerts* /api/v1/alert-rules* /api/v1/alert-types* /api/v1/alert-view/* /api/v1/docs/c2* /api/v1/health/c2
  handle @c2 { reverse_proxy c2-alerts:8002 }
  @c3 path /api/v1/inference/* /api/v1/media-events/* /api/v1/models* /api/v1/records/* /api/v1/detections/* /api/v1/data-dictionary* /api/v1/integrity-* /api/v1/activity-patterns* /api/v1/docs/c3* /api/v1/health/c3
  handle @c3 { reverse_proxy c3-data:8003 }
  handle { root * /srv/web; try_files {path} /index.html; file_server }
  request_body { max_size 60MB }
}
```
`SITE_ADDRESS` is `:80` locally and the domain (e.g. `homeai-team.duckdns.org`) on EC2 so Caddy gets a
Let's Encrypt certificate automatically. Without a domain, use `:80` (HTTP) for the demo.

---
## 5. Environment variables (`.env.example`)
```
ENV=local                      # local | aws
PUBLIC_BASE_URL=http://localhost:8080
SITE_ADDRESS=:80
AWS_REGION=us-west-2
AWS_ENDPOINT_URL=http://localstack:4566     # empty on AWS
S3_BUCKET=homeai-local
JWKS_URL=http://c4-dashboard:8004/.well-known/jwks.json
C4_BASE_URL=http://c4-dashboard:8004
C1_BASE_URL=http://c1-iot:8001
C2_BASE_URL=http://c2-alerts:8002
C3_BASE_URL=http://c3-data:8003
MONGO_URL_C1=mongodb://c1_app:***@mongo:27017/homeai
MONGO_URL_C2_READER=mongodb://c2_reader:***@mongo:27017/homeai
MONGO_URL_C3=mongodb://c3_app:***@mongo:27017/homeai
MONGO_URL_C4=mongodb://c4_app:***@mongo:27017/homeai
DATABASE_URL_C1=postgresql+psycopg://c1_app:***@postgres:5432/homeai
DATABASE_URL_C2=postgresql+psycopg://c2_app:***@postgres:5432/homeai
DATABASE_READER_URL_C2=postgresql+psycopg://c2_reader:***@postgres:5432/homeai
DATABASE_URL_C3=postgresql+psycopg://c3_app:***@postgres:5432/homeai
DATABASE_READER_URL_C3=postgresql+psycopg://c3_reader:***@postgres:5432/homeai
DATABASE_URL_C4=postgresql+psycopg://c4_app:***@postgres:5432/homeai
C4_JWT_PRIVATE_KEY_SECRET=homeai/jwt-signing-key   # Secrets Manager id (LocalStack locally)
C2_ALERT_VIEW_KEY_SECRET=homeai/alert-view-hmac
SERVICE_CLIENT_SECRET_C2=***   SERVICE_CLIENT_SECRET_C3=***   SERVICE_CLIENT_SECRET_C4=***   SERVICE_CLIENT_SECRET_DEVICE=***
NOTIFIER=log                   # log | sns
C3_MODEL_DIR=/models
DEMO_MODE=1                    # enables /dev helpers; MUST be 0 in production
```
On EC2 the `.env` is produced by `infra/aws/render_env.sh`, which reads secrets from Secrets Manager.

---
## 6. Makefile targets
| Target | Does |
|---|---|
| `make up` / `make down` | start/stop the local stack |
| `make migrate` | run Alembic for all services |
| `make seed` | `python scripts/seed.py` (idempotent) |
| `make token ROLE=house_owner` / `make token CLIENT=c3-worker` | print a dev JWT |
| `make test` / `make test-c2` | pytest for all / one service (uses compose Postgres/Mongo, test databases) |
| `make lint` | ruff + `npm run lint` + `npm run typecheck` |
| `make web` | `npm run dev` in `web/` (Vite proxy `/api` and `/.well-known` → `http://localhost:8080`) |
| `make demo-clips` | `scripts/fetch_demo_clips.sh` |
| `make deploy` | SSH to EC2: `git pull && docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml up -d --build` |

---
## 7. Seed data (`scripts/seed.py`, fixed UUIDs so docs and demos can reference them)
The fixed IDs live in **`scripts/seed_ids.py`** (tenants `11111111-…`, houses `22222222-…`, rooms `33333333-…`, users `44444444-…`, Maple contacts `55555555-…`); `seed.py`, demo scripts and tests import them from there. C2's rules: `docker compose exec c2-alerts python -m app.seed`.
| Kind | Seed |
|---|---|
| Tenants | `Acme Care` (`11111111-...-0001`), `Sunrise Living` (`...-0002`) for isolation tests |
| Users (password `Demo!2026` in dev only) | `owner.maple@acme.test` (house_owner, Maple St), `owner.oak@acme.test` (house_owner, Oak Ave), `iot@acme.test` (iot_staff, Acme), `ops@homeai.test` (cloud_staff), `owner.sun@sunrise.test` (house_owner, Sunrise) |
| Houses | Maple St (America/Los_Angeles), Oak Ave (America/Los_Angeles) in Acme; Pine Rd in Sunrise |
| Rooms | Kitchen, Bedroom 1, Living, Bathroom, Entryway per house |
| Feeds | Kitchen Mic (audio, enabled), Front Door Cam (video, enabled), Garage Cam (video, enabled, no clips → inactive), Nursery Mic (audio, provisioned, no room) |
| Settings | Maple: all services on, quiet 22:00–07:00, medium; Oak: wellness off, high |
| Contacts | Maple: 3 contacts (use real team emails for the demo; confirm SNS subscriptions in advance) |
| Alert types + tenant default rules | the 7 rows of the mapping table in `02_CONTRACTS.md` |
| ML model | `yamnet 1.0.0` active with the 7-label map |
| Service clients | `c2-alerts`, `c3-worker`, `c3-data`, `c4-dashboard`, `device-uploader` |
| Demo clips | `demo_clips/{smoke_alarm,scream,glass_break,thud,cough,speech,dog,silence}.wav` |
Seed order: C4 (tenants, users, settings, contacts, service clients) → C1 (houses, rooms, feeds) via API →
C2 (alert types, rules) → C3 (model). Houses created in C1 use IDs that C4 settings reference, so the seed
creates houses first with fixed IDs through C1's API (`house_id` accepted only when `DEMO_MODE=1`).

`scripts/fetch_demo_clips.sh` downloads selected public clips from the ESC-50 dataset (CC BY-NC, academic
use; credit in the README): dog, glass_breaking, coughing, crying_baby/scream-like, door_wood_knock (thud),
and generates a 3 kHz beep pattern as a smoke-alarm stand-in with Python/numpy. All clips are converted to
16 kHz mono WAV, 5–10 s.

---
## 8. AWS setup (one-time, ~2 hours; do it in week 3 so everyone tests on AWS before the demo)
1. **Account and region**: pick `us-west-2`; enable billing alerts and a $25 budget alarm.
2. **S3**: create bucket `homeai-<team>-<accountid>`; Block Public Access ON; default encryption SSE-S3;
   lifecycle: `tenants/` → Standard-IA after 30 days, expire after 365 days; `backups/` expire after 14 days.
3. **RDS**: PostgreSQL 16, `db.t4g.micro`, 20 GB gp3, no public access, default VPC, new SG `homeai-rds`
   (inbound 5432 from SG `homeai-ec2` only). Master user stored in Secrets Manager. Run `infra/db/init.sql`
   once from the EC2 host (`psql`).
4. **Secrets Manager**: `homeai/db/<role>` for each DB role, `homeai/mongo/<user>`, `homeai/jwt-signing-key`
   (RSA private PEM; generate with `openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048`),
   `homeai/alert-view-hmac` (32 random bytes, base64), `homeai/service-clients` (JSON of client secrets).
5. **IAM role** `homeai-ec2-role` (instance profile) with `infra/aws/ec2-policy.json`:
   S3 Get/Put/Delete/List on the bucket; SNS CreateTopic, Subscribe, ListSubscriptionsByTopic,
   SetSubscriptionAttributes, Publish on `arn:aws:sns:<region>:<acct>:homeai-*`; SecretsManager
   GetSecretValue on `homeai/*`; CloudWatch Logs CreateLogStream/PutLogEvents (optional).
6. **EC2**: Ubuntu 22.04, `t3.large`, 40 GB gp3, SG `homeai-ec2` (80, 443 from 0.0.0.0/0; 22 from team IPs),
   attach the IAM role, Elastic IP. Install Docker + compose plugin, `git`, `postgresql-client`, `awscli`.
   Clone the repo, run `infra/aws/render_env.sh > .env`, then `make deploy`.
7. **Domain/TLS (optional but recommended)**: free DuckDNS subdomain → Elastic IP; set `SITE_ADDRESS`.
8. **SNS**: nothing to pre-create — C2 creates `homeai-house-<house_id>` topics and subscriptions. Before the
   demo, run C2's subscription sync and **click the confirmation emails** for each demo contact.
9. **Backups**: C3 backup job writes nightly `pg_dump` and `mongodump` to S3; also enable RDS automated
   backups (7 days).
10. **Cost control**: stop EC2 and RDS when not demoing (RDS stays stopped up to 7 days); delete everything after grading.

---
## 9. CI/CD — `.github/workflows/ci.yml`
- Trigger: pull requests and pushes to `main`.
- Jobs: `lint` (ruff, eslint, tsc) → `test-python` (matrix c1..c4 + common; services: postgres:16, mongo:7;
  run Alembic then pytest with coverage ≥ 70% per service) → `test-web` (vitest) → `build-images`
  (docker build for each service; C3 image cached).
- Branching: `main` protected; feature branches `c2/alert-rules-api`; one reviewer from another component.
- Deploy: manual `make deploy` (or a `workflow_dispatch` job that SSHes to EC2 with a deploy key).

---
## 10. Phase 0 tasks (week 1, whole team; IDs used in the roadmap)
| ID | Task | Owner | Done when |
|---|---|---|---|
| P0-1 | Create GitHub repo, branch protection, issue labels `C1..C4`, project board | Mohit | Repo exists, all members admin |
| P0-2 | Monorepo skeleton (section 1), `pyproject.toml` with ruff, `.env.example`, Makefile | Mohit | `make lint` runs |
| P0-3 | `homeai_common` modules config, errors, pagination, logging, health, db, mongo, s3 | Prathamesh | Unit tests green |
| P0-4 | `homeai_common.auth` + `service_client` + `testing` | Mohit | Unit tests green incl. revoked/expired |
| P0-5 | `infra/docker-compose.yml`, `db/init.sql`, `mongo/init.js`, `localstack/init-aws.sh` | Renuka | `make up` brings all infra healthy |
| P0-6 | Service skeletons c1..c4: `create_app`, health router, settings, Alembic baseline, Dockerfile | each owner | `GET /api/v1/health/cX` 200 through Caddy |
| P0-7 | C4 minimum auth: tenants/users tables, `POST /auth/login`, JWKS, `POST /auth/service-token`, `/auth/revoked` | Mohit | Other services verify a real token |
| P0-8 | Web skeleton: Vite + TS + Tailwind + Router + Query; AppShell, Login page, RouteGuard, API client | Mohit | Login works, role landing routes exist |
| P0-9 | Caddyfile + `infra/caddy/Dockerfile` | Renuka | Routing table in 01 works |
| P0-10 | `scripts/seed.py` skeleton + `mint_token.py` | Ekant | Seeded users can log in |
| P0-11 | CI workflow | Prathamesh | PR shows green checks |
| P0-12 | `scripts/fetch_demo_clips.sh` and `demo_clips/` | Renuka | 8 clips at 16 kHz mono |
