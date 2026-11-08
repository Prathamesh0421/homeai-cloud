# C4 work log (Mohit — System Dashboard)

Living changelog for teammates. Update this file in the same PR whenever a C4
task lands. Newest pass at the top of the "Passes" section.

**How to use this:** skim the latest pass for new endpoints, seed commands, and
anything you can call from C1/C2/C3. Older passes stay for history.

---

## Passes

### C4-16 follow-up — 8 Nov 2026 (EC2 first deploy)

| ID | What landed |
|---|---|
| C4-16 | First EC2 deploy on Free Tier (`t3.micro` + RDS `db.t3.micro`). Smoke green: C4 health, login, JWKS, `/auth/me`, SNS list-topics. |
| fix | `render_env.sh` embeds real Secrets Manager DB/Mongo/service-client passwords (no `${PLACEHOLDER}`), includes C3 URLs, clears `AWS_ENDPOINT_URL` / `C4_AWS_ENDPOINT_URL` for real AWS; pairs with `set_passwords.sh` from `make deploy`. |
| fix | C4 `Settings` now subclasses `homeai_common.config.BaseServiceSettings` so unprefixed `DEMO_MODE`, `AWS_ENDPOINT_URL`, `DATABASE_URL_C4` work; secrets gateway treats empty endpoint as real AWS (fixes login 500 that hit LocalStack). |
| fix | `make seed-c4-docker` runs Alembic + seed inside the C4 container (host has no `alembic`); mounts repo for `scripts/seed_ids.py`. |
| shell | `/ops/models` and `/ops/records` routes added as C3 placeholders (sidebar links no longer bounce to System Dashboard). |

**Teammate notes**
- On EC2: `make deploy-env > .env`, then compose with `--profile gateway`; seed with `make seed-c4-docker` (not host `make seed-c4`).
- Demo URL: EC2 EIP on :80. Login `ops@homeai.test` / `Demo!2026`.
- C1/C3 still not on the host; Alerts/Rules may error until C2 seed + SNS confirm + C1 houses exist.
- Rebuild Caddy after pulling `web/src/App.tsx` so Models/Records placeholders appear.

### C4-16 — 7 Nov 2026 (AWS setup artifacts)

| ID | What landed |
|---|---|
| C4-16 | AWS provisioning + deploy artifacts under `infra/aws/`: `provision.sh` (S3, RDS, Secrets Manager, IAM role, EC2 + EIP, $25 budget), `ec2-policy.json` (least-privilege IAM — S3, SNS incl. Unsubscribe/GetSubscriptionAttributes/ListTopics per `07` §5, Secrets Manager `homeai/*`), `ec2-trust-policy.json`, `s3-lifecycle.json`, `render_env.sh` (prints prod `.env` from provisioned resources), `smoke.sh` (post-deploy checks), `README.md` runbook. `infra/docker-compose.prod.yml` overlay (no LocalStack/Postgres, Mongo on host, Caddy 80/443, `NOTIFIER=sns`, `HANDOFF_MODE=call`). `make deploy` / `deploy-env` / `deploy-down` / `deploy-logs` targets. |

**Teammate notes**
- Run `infra/aws/provision.sh` once (admin machine, not EC2) with `TEAM=… KEY_NAME=…`. Prints the EC2 EIP + RDS endpoint.
- On EC2: `make deploy-env > .env` (with `RDS_ENDPOINT` + `SITE_ADDRESS`), then `make deploy`, then `make seed-c4-docker` against RDS.
- `infra/aws/smoke.sh` checks health, login, JWKS, `/auth/me`, and SNS IAM role.
- Fixes found while smoke-testing: `UserPublic.tenant_id` is now `str | None` (cloud_staff have no tenant); `conftest` drops the `c4.users_public` view before `BASE_METADATA.drop_all`.
- `SKIP_RDS=1` keeps Postgres as a container on EC2 if RDS is slow (`07` §3 fallback).
- Tests: 54 C4 (no new tests; smoke is a script). `ruff` clean.

### Week 2 — 5 Nov 2026 (settings, tenants, seed, UI kit)

| ID | What landed |
|---|---|
| C4-06 | Settings + emergency-contacts APIs. `GET/PUT /api/v1/houses/{id}/settings` (defaults when no row). Contacts CRUD + `PUT .../emergency-contacts/order`. Owner via `assert_house`; cloud_staff bypass. |
| C4-07 | Tenants/users admin (cloud_staff only). `GET/POST /tenants`, `GET/POST /tenants/{id}/users`, `PATCH /users/{id}`. Password ≥ 10 with letters+digits. Best-effort C2 `POST /alert-rules/defaults` after tenant create. Migration `0003`: `users.tenant_id` nullable for platform staff. |
| C4-15 | Idempotent seed: `make seed-c4` (runs the C4 migrations, then `python -m app.seed` from `services/c4_dashboard`, `PYTHONPATH` = repo root). Uses `scripts/seed_ids.py`. Password `Demo!2026`. Service clients get the scopes of contract §2.3; secrets from the `.env.example` names (`SERVICE_CLIENT_SECRET_C2` → c2-alerts, `_C3` → c3-worker + c3-data, `_C4` → c4-dashboard, `_DEVICE` → device-uploader; dev defaults `dev-c2-secret` etc.). |
| C4-11 | Shared UI kit in `web/src/shared` + typed helpers in `web/src/api/c4.ts` (settings/contacts/tenants/users). Pages still placeholders until C4-12/14. |

**Teammate notes**
- C2 can keep reading `c4.house_service_settings` / `emergency_contacts` after `make seed-c4`.
- Demo login: `owner.maple@acme.test` / `Demo!2026`; ops: `ops@homeai.test` / `Demo!2026`.
- Service token: client `c4-dashboard`, secret `dev-c4-secret` (unless `SERVICE_CLIENT_SECRET_C4` is set), scopes `feeds:read`, `alerts:read`, `records:read`.
- Seed fixes (5 Nov, Prathamesh; commit note has details): scopes now follow contract §2.3 (they did not match any caller, so e.g. C3's `alerts:evaluate` handoff token was refused), secrets use the `.env.example` names, the seed no longer creates the schema/tables (that failed as `c4_app` and skipped the migrations' reader grants), and Maple/Oak settings match docs/03 §7.
- Tests this pass: 50 C4 + 9 web. `ruff` / `eslint` / `tsc` clean.

### Week 1 — 2 Nov 2026 (auth foundation)

| ID | What landed |
|---|---|
| P0-2 | Root `pyproject.toml` (ruff), `.env.example`, `Makefile` |
| C4-01 | FastAPI app, `GET /api/v1/health/c4`, Dockerfile, Alembic |
| C4-02 | Schema `c4` + `GET /.well-known/jwks.json` |
| C4-03 | Login / logout / me / revoked |
| C4-04 | Service-token issuance |
| C4-05 | `libs/homeai_common`: `auth`, `service_client`, `testing` |
| C4-10 | Vite shell: login, `RouteGuard`, role landings |

---

## Still open (later weeks)

C4-08/09 dashboards + rollup · C4-12–14 feature pages · C4-17 Playwright.
Master `scripts/seed.py` stays with its Phase 0 owner; until then use `make seed-c4` (local) or `make seed-c4-docker` (EC2).
C4-16 provision + first EC2 smoke are done (8 Nov); C1/C3 still need to join the stack for the full clip→alert path.
