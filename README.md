# HomeAI Cloud

Multi-tenant smart-home monitoring platform. Built for **CMPE 281 (Cloud Technologies), SJSU, Fall 2026**.

Homes upload short audio/video clips from their camera feeds. The clips are classified with the pre-trained
**YAMNet** audio model, alert rules turn the results into **alerts**, and **Amazon SNS** emails the
house's emergency contacts. Owners then acknowledge and resolve the alerts from a web dashboard.

> **Status:** Phase 0 (foundation), started 2 Nov 2026. The quick-start commands below describe the target
> setup. They will work once the Phase 0 tasks in [`docs/03_REPO_AND_INFRA.md`](docs/03_REPO_AND_INFRA.md) §10 are done.

---

## How it works

```
Device / IoT staff ──upload clip──▶ C1 IoT ──▶ S3 + MongoDB media_events (queued)
                                                     │
                                       C3 worker ◀───┘  YAMNet → 7 home labels → ai_detections
                                           │
                                           ▼
                                C2 Alerts  rules + house settings + quiet hours → alert
                                           │
                                           ├──▶ SNS email to emergency contacts (signed 24 h link)
                                           ▼
                                Owner dashboard (C4 shell) → acknowledge → resolve
```

The full design is in [`docs/01_ARCHITECTURE.md`](docs/01_ARCHITECTURE.md).

## Components and team

| Code | Component | Owner | Service (port) | UI folder |
|---|---|---|---|---|
| C1 | Home-Based IoT Device Manager | Ekant Kapgate | `services/c1_iot` (8001) | `web/src/features/c1-iot` |
| C2 | Alert Tracking and Monitor | Prathamesh Ravindra Sawant | `services/c2_alerts` (8002) | `web/src/features/c2-alerts` |
| C3 | System Database Management (incl. AI inference) | Renuka Prasad Patwari | `services/c3_data` (8003) + `c3-worker` | `web/src/features/c3-data` |
| C4 | System Dashboard (auth, RBAC, settings, dashboards, app shell) | Mohit Manoj Barade | `services/c4_dashboard` (8004) | `web/src/features/c4-dashboard`, `web/src/shared` |

## Tech stack

- **Backend:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2 + psycopg 3, Alembic, PyMongo, APScheduler
- **AI (C3):** TensorFlow (CPU) + TensorFlow Hub YAMNet, numpy, soundfile, ffmpeg
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, React Router, TanStack Query, Recharts
- **Data:** PostgreSQL 16 (one schema per component), MongoDB 7
- **Auth:** RS256 JWTs issued by C4, verified by every service through JWKS
- **Runtime:** Docker Compose behind a Caddy reverse proxy. Locally, LocalStack stands in for S3, SNS and
  Secrets Manager. On AWS: one EC2 host, RDS PostgreSQL, S3, SNS and Secrets Manager.

## Repository layout

```
homeai-cloud/
├── AGENTS.md            # rules for AI coding assistants (read first)
├── docs/                # implementation plan: architecture, contracts, per-component plans
├── libs/homeai_common/  # shared Python library: auth, errors, pagination, logging, db, clients
├── services/            # c1_iot, c2_alerts, c3_data, c4_dashboard (FastAPI apps)
├── web/                 # React SPA
├── infra/               # docker-compose, Caddy, DB/Mongo init, LocalStack, AWS scripts
└── scripts/             # seed, token minting, device simulator, demo helpers
```

## Quick start (local)

Prerequisites: Docker with the Compose plugin, Python 3.11, Node 20, GNU Make.

```bash
cp .env.example .env      # local defaults; never commit .env
make up                   # postgres, mongo, localstack, the four services, caddy
make migrate              # Alembic migrations for every service
make seed                 # demo tenants, users, houses, feeds, rules, model
make demo-clips           # download/generate demo audio into ./demo_clips
```

- App and API gateway: <http://localhost:8080>
- API docs: `http://localhost:8080/api/v1/docs/c1` … `/c4`
- Health: `http://localhost:8080/api/v1/health/c1` … `/c4`
- Frontend with hot reload: `make web` (Vite on <http://localhost:5173>, proxies `/api` to the gateway)

### Common commands

| Command | What it does |
|---|---|
| `make up` / `make down` | Start or stop the local stack |
| `make test` / `make test-c2` | Run all tests, or one service's tests |
| `make lint` | ruff, eslint and TypeScript type-check |
| `make token ROLE=house_owner` | Print a dev JWT for a seeded user |
| `make token CLIENT=c3-worker` | Print a dev service token |
| `make reset-demo` | Clear alerts, clips and detections, then reseed (keeps users) |
| `make deploy` | Pull and rebuild on the EC2 host |

### Demo accounts (local/dev only)

All seeded users share the dev password `Demo!2026`. It is never used on a shared deployment.

| Email | Role | Scope |
|---|---|---|
| `owner.maple@acme.test` | house_owner | Maple St (Acme Care) |
| `owner.oak@acme.test` | house_owner | Oak Ave (Acme Care) |
| `iot@acme.test` | iot_staff | Acme Care tenant |
| `ops@homeai.test` | cloud_staff | All tenants |
| `owner.sun@sunrise.test` | house_owner | Pine Rd (Sunrise Living), for tenant-isolation tests |

## Documentation

Read these in order before you contribute:

1. [`AGENTS.md`](AGENTS.md): hard rules, stack, definition of done
2. [`docs/01_ARCHITECTURE.md`](docs/01_ARCHITECTURE.md): components, data ownership, clip-to-alert flow
3. [`docs/02_CONTRACTS.md`](docs/02_CONTRACTS.md): **binding** API conventions, JWT claims, enums, payloads
4. [`docs/03_REPO_AND_INFRA.md`](docs/03_REPO_AND_INFRA.md): repo layout, shared library, Docker, AWS, CI
5. [`docs/04_FRONTEND.md`](docs/04_FRONTEND.md): SPA structure, routes, shared UI kit
6. Component plans: [C1](docs/components/C1_IOT_DEVICE_MANAGER.md) ·
   [C2](docs/components/C2_ALERT_TRACKING.md) · [C3](docs/components/C3_DATABASE_AND_AI.md) ·
   [C4](docs/components/C4_DASHBOARD_AND_AUTH.md)
7. [`docs/05_INTEGRATION_AND_TESTING.md`](docs/05_INTEGRATION_AND_TESTING.md) and
   [`docs/06_ROADMAP_AND_DEMO.md`](docs/06_ROADMAP_AND_DEMO.md)

Changes to contracts are recorded in [`docs/CHANGELOG.md`](docs/CHANGELOG.md).

## Contributing

- Branch from `main` and name branches `<component>/<topic>`, e.g. `c2/alert-rules-api`.
- Open a pull request. CI must be green and a member of another component must review it.
- Change only your own component's folders. Changes to `libs/homeai_common`, `web/src/shared`, `infra/` or
  another component need that owner's review.
- No secrets in git. Configuration comes from environment variables; the template is `.env.example`.

## Credits

- **YAMNet**: Google, trained on [AudioSet](https://research.google.com/audioset/). Model via TensorFlow Hub (Apache 2.0).
- **ESC-50**: K. J. Piczak, *ESC: Dataset for Environmental Sound Classification* (CC BY-NC 3.0).
  Used for demo and evaluation clips, academic use only.
