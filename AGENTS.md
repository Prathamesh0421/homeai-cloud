# AGENTS.md — Instructions for AI coding assistants working on HomeAI Cloud

> Copy this file to the repo root. If your assistant reads a different file name, also copy it to
> `CLAUDE.md` (Claude Code) or `.github/copilot-instructions.md` (GitHub Copilot). Keep them identical.

## 1. What this project is
HomeAI Cloud is a multi-tenant smart-home platform (CMPE 281, SJSU, Fall 2026). Audio/video clips from
home "camera feeds" are uploaded, classified with the pre-trained **YAMNet** audio model, turned into
**alerts** by rules, and emailed to emergency contacts. Four components, one per team member:

| Code | Component | Owner | Service folder | UI folder |
|---|---|---|---|---|
| C1 | Home-Based IoT Device Manager | Ekant Kapgate | `services/c1_iot` | `web/src/features/c1-iot` |
| C2 | Alert Tracking and Monitor | Prathamesh Ravindra Sawant | `services/c2_alerts` | `web/src/features/c2-alerts` |
| C3 | System Database Management (incl. AI inference) | Renuka Prasad Patwari | `services/c3_data` | `web/src/features/c3-data` |
| C4 | System Dashboard (auth, RBAC, settings, dashboards, app shell) | Mohit Manoj Barade | `services/c4_dashboard` | `web/src/features/c4-dashboard` + `web/src/shared` |

> **The component demos took place on Wed 11 Nov 2026.** `docs/07_DEMO_NOV_11.md` only set priorities until
> then and no longer applies (it is kept for its record and AWS notes). Work now follows the original plan:
> `docs/06_ROADMAP_AND_DEMO.md` (including §6, final project) and the task lists in the component plans.
> The **final project presentation is Wed 2 Dec 2026** (see the course-dates note at the top of `06`).

## 2. Read these before writing code (in this order)
1. `docs/01_ARCHITECTURE.md` — system shape, data ownership, the clip-to-alert flow.
2. `docs/02_CONTRACTS.md` — **binding** API conventions, JWT claims, enums, cross-component payloads.
3. `docs/03_REPO_AND_INFRA.md` — repo layout, shared library, Docker Compose, AWS.
4. `docs/04_FRONTEND.md` — SPA structure, routes, shared UI components.
5. Your component plan in `docs/components/Cx_*.md` — scope, data model, endpoints, jobs, UI, tests, tasks.
6. `docs/05_INTEGRATION_AND_TESTING.md` and `docs/06_ROADMAP_AND_DEMO.md` when integrating or preparing demos.

The approved design (Deliverable #2 PDF) is the source of truth for intent; these docs are the source of
truth for implementation details. Where they differ, these docs win (they record D3 decisions).

## 3. Hard rules
- **Contracts are frozen.** Do not change any path, field name, enum value, status code or payload in
  `docs/02_CONTRACTS.md` or in a component's "API" section without the owner's agreement. If a change is
  agreed, update the doc in the same pull request and add a line to `docs/CHANGELOG.md`.
- **Stay in your lane.** Only edit your component's service folder, your UI feature folder, your
  migrations and your tests. Changes to `libs/homeai_common`, `web/src/shared`, `infra/` or another
  component need a pull request reviewed by that owner.
- **Never write to another component's data.** Cross-component reads go through the read-only DB roles or
  the other component's REST API exactly as documented. Writes always go through the owning component's API.
- **No secrets in git.** Read configuration from environment variables (`.env` locally, generated on EC2).
- **Every endpoint**: Pydantic request/response models, the shared error envelope, a scope/role check via
  `homeai_common.auth`, pagination where it returns a list, and at least one happy-path and one error-path test.
- **IDs are UUID v4 strings everywhere** (PostgreSQL `UUID`, MongoDB `_id` as string). Times are UTC,
  ISO-8601 with `Z`.
- **Route order**: declare static paths (`/feeds/stats`, `/alerts/stats`, `/models/classes`, `/models/active`,
  `/models/deployment`) before parameterised ones (`/feeds/{id}`, `/alerts/{id}`, `/models/{id}`).
- **Tenant isolation**: every query filters by the caller's `tenant_id` (and `house_ids` for owners).
  Write a test that proves a user of tenant A cannot read tenant B.

## 4. Tech stack (fixed)
- Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.x (sync) + psycopg 3, Alembic, PyMongo, boto3, httpx,
  PyJWT[crypto], bcrypt, APScheduler, python-json-logger, pytest.
- C3 additionally: tensorflow-cpu + tensorflow-hub (YAMNet), numpy, soundfile, ffmpeg (system package).
- Frontend: React 18 + TypeScript + Vite, Tailwind CSS, React Router, TanStack Query, react-hook-form + zod,
  Recharts, Vitest + Testing Library, Playwright for end-to-end demo flows.
- Runtime: Docker Compose (local and on one AWS EC2 host), Caddy reverse proxy, AWS RDS PostgreSQL,
  MongoDB container, S3, SNS, Secrets Manager. LocalStack replaces S3/SNS/Secrets Manager locally.

## 5. Code style
- `ruff check` and `ruff format` must pass (config in `pyproject.toml`). Type hints on all public functions.
- Layering per service: `api/` (routers) → `services/` (business logic) → `repositories/` (DB) and
  `gateways/` (other components, AWS). Routers contain no business logic. Repositories contain no HTTP.
- Names follow the class diagrams in the design (e.g. `RuleEngine`, `IngestService`, `ClassificationPipeline`).
- Frontend: function components + hooks, one folder per page, API calls only through `web/src/api/*`.
  Run `npm run lint` and `npm run typecheck`.

## 6. Definition of done for any task
1. Code + migrations + tests merged on `main` through a pull request with green CI.
2. OpenAPI docs render at `/api/v1/docs/<cx>` and match the component plan.
3. The UI path for the feature works against the local Docker stack with seed data.
4. The component plan's acceptance checklist item is ticked.
