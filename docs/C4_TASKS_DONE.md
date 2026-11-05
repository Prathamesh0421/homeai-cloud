# C4 work log (Mohit — System Dashboard)

Living changelog for teammates. Update this file in the same PR whenever a C4
task lands. Newest pass at the top of the "Passes" section.

**How to use this:** skim the latest pass for new endpoints, seed commands, and
anything you can call from C1/C2/C3. Older passes stay for history.

---

## Passes

### Week 2 — 5 Nov 2026 (settings, tenants, seed, UI kit)

| ID | What landed |
|---|---|
| C4-06 | Settings + emergency-contacts APIs. `GET/PUT /api/v1/houses/{id}/settings` (defaults when no row). Contacts CRUD + `PUT .../emergency-contacts/order`. Owner via `assert_house`; cloud_staff bypass. |
| C4-07 | Tenants/users admin (cloud_staff only). `GET/POST /tenants`, `GET/POST /tenants/{id}/users`, `PATCH /users/{id}`. Password ≥ 10 with letters+digits. Best-effort C2 `POST /alert-rules/defaults` after tenant create. Migration `0003`: `users.tenant_id` nullable for platform staff. |
| C4-15 | Idempotent seed: `make seed-c4` or `python -m app.seed` (from `services/c4_dashboard`, `PYTHONPATH` = repo root). Uses `scripts/seed_ids.py`. Password `Demo!2026`. Service secrets from `SERVICE_CLIENT_SECRET_*` (default `dev-<client>-secret`). |
| C4-11 | Shared UI kit in `web/src/shared` + typed helpers in `web/src/api/c4.ts` (settings/contacts/tenants/users). Pages still placeholders until C4-12/14. |

**Teammate notes**
- C2 can keep reading `c4.house_service_settings` / `emergency_contacts` after `make seed-c4`.
- Demo login: `owner.maple@acme.test` / `Demo!2026`; ops: `ops@homeai.test` / `Demo!2026`.
- Service token: client `c4-dashboard`, secret `dev-c4-dashboard-secret` (unless env override).
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

C4-08/09 dashboards + rollup · C4-12–14 feature pages · C4-16 AWS · C4-17 Playwright.
Master `scripts/seed.py` stays with its Phase 0 owner; until then use `make seed-c4`.
