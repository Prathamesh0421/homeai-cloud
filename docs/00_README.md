# HomeAI Cloud — Implementation Plan (Deliverable #3 and final project)

This folder is the complete implementation plan for HomeAI Cloud. It is written so that a team member
**or an AI coding assistant** can build each component without guessing.

## How to use it
1. Put `AGENTS.md` at the repository root and this `docs/` folder next to it.
2. Each member opens their AI assistant in the repo and starts with:
   *"Read AGENTS.md and docs/00–04, then docs/components/<your file>. Implement task <ID> from the task list."*
3. Work through your component's task list **in order**. Each task names the files to create, what they do,
   and how to test it. Tick the acceptance checklist as you go.
4. Integration and demos follow `05_INTEGRATION_AND_TESTING.md` and `06_ROADMAP_AND_DEMO.md`.

## Files
| File | What it covers | Who reads it |
|---|---|---|
| `../AGENTS.md` | Rules for AI assistants; stack; definition of done | Everyone, every session |
| `01_ARCHITECTURE.md` | Components, data ownership, end-to-end flows, deployment topology | Everyone |
| `02_CONTRACTS.md` | Binding conventions: envelope, errors, JWT, roles, scopes, enums, cross-component payloads | Everyone |
| `03_REPO_AND_INFRA.md` | Monorepo layout, shared Python library, Docker Compose, env vars, seed data, AWS setup, CI/CD | Everyone; C4 owner leads setup |
| `04_FRONTEND.md` | React SPA structure, routes, shared UI kit, API client | Everyone doing UI |
| `components/C1_IOT_DEVICE_MANAGER.md` | C1 full plan | Ekant |
| `components/C2_ALERT_TRACKING.md` | C2 full plan | Prathamesh |
| `components/C3_DATABASE_AND_AI.md` | C3 full plan incl. model management and deployment | Renuka |
| `components/C4_DASHBOARD_AND_AUTH.md` | C4 full plan incl. shared app shell | Mohit |
| `05_INTEGRATION_AND_TESTING.md` | Test strategy, contract tests, E2E scenarios, seed/demo data | Everyone |
| `06_ROADMAP_AND_DEMO.md` | Week-by-week schedule, dependencies, component demo + video scripts, final project | Everyone |

## Deliverable #3 (component demo) — what graders check
| Criterion | Points | What we must show |
|---|---|---|
| Component live demo | 3 | Required component functions working end to end **with UI and backend** |
| Component scenario demo (video) | 2 | A recorded scenario showing the required functions and UI |
| AI component extra | — | C3 must also show **UI, model management and deployment** |

Every component plan has a **Demo** section with a live-demo script and a video script mapped to these points.

## Decisions taken for implementation (recorded here, binding)
- Backend: **Python 3.11 + FastAPI** for all four components; C3 worker in the same codebase.
- Runtime: **AWS EC2 + Docker Compose**, RDS PostgreSQL, MongoDB container, S3, SNS, Secrets Manager.
- One React SPA; each member owns a feature folder; C4 owns the shell and shared UI kit.
- Additions beyond the D2 design (needed for D3 demos and dashboards) are marked **[D3 addition]** in the
  component plans: C3 model registry and test-classify endpoints; C1 `GET /feeds/stats`; C3
  `GET /detections/stats`; C2 contact-subscription sync job; dev-only demo helpers.
