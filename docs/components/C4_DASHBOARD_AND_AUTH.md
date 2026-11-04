# C4 — System Dashboard (identity, RBAC, settings, dashboards, app shell) — Implementation Plan
**Owner:** Mohit Manoj Barade · **Service:** `services/c4_dashboard` (port 8004) · **UI:** `web/src/features/c4-dashboard` + `web/src/shared` + `web/src/auth`
**Reads first:** `AGENTS.md`, `docs/01`–`04`. Design reference: D2 Part IV (C4).

## 0. Goal in one line
Sign users in and issue RS256 JWTs (and service tokens) that every component verifies via JWKS, enforce RBAC,
store house service settings and ordered emergency contacts, roll up and present role dashboards, and provide
the SPA shell, route guard and shared UI kit.

> C4 is on everyone's critical path: **P0-7 (minimum auth) and P0-8 (web shell) must be done in week 1.**

---
## 1. Scope
**In:** tenants, users, login + lockout, logout + revocation list, `/auth/me`, service tokens, JWKS, house
service settings, emergency contacts (max 5, ordered), dashboard summary (daily rollup + live counts),
StatsRollupJob, tenants & users admin, SPA shell/auth/route guard/shared UI kit, Home Overview, Services and
Settings, System Dashboard, Tenants and Users pages; leads AWS setup.
**Out:** feeds (C1), alerts and rules (C2), records/AI (C3).

### 1.1 Dependencies
| Needs | From | Stub until ready |
|---|---|---|
| House list/timezones (validate `house_ids`, settings tenant) | `c1.houses` (read-only role `c4_reader`) | seed rows |
| Feed stats | C1 `GET /feeds/stats` (svc `feeds:read`) | zeros + "unavailable" badge |
| Alert stats + recent/open alerts | C2 `GET /alerts/stats`, `GET /alerts` (svc `alerts:read`) | zeros |
| Detection stats, activity | C3 `GET /detections/stats`, `GET /activity-patterns` (svc `records:read`) | zeros |
| **Provides** | **To** | |
| JWKS, login, service tokens, revoked list, `homeai_common.auth` | everyone (week 1) | |
| `c4.house_service_settings`, `c4.emergency_contacts` read-only | C2 | |
| App shell, RouteGuard, shared UI kit | all UI pages | |

---
## 2. Data model — schema `c4`
```sql
CREATE TABLE c4.tenants (
  tenant_id UUID PRIMARY KEY, name VARCHAR(80) NOT NULL UNIQUE, timezone VARCHAR(40) NOT NULL,
  status VARCHAR(10) NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE EXTENSION IF NOT EXISTS citext;
CREATE TABLE c4.users (
  user_id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES c4.tenants(tenant_id),
  email CITEXT NOT NULL UNIQUE, password_hash VARCHAR(100) NOT NULL,
  role VARCHAR(12) NOT NULL CHECK (role IN ('house_owner','iot_staff','cloud_staff')),
  display_name VARCHAR(80), house_ids UUID[] NOT NULL DEFAULT '{}',
  is_active BOOLEAN NOT NULL DEFAULT true, failed_attempts SMALLINT NOT NULL DEFAULT 0,
  first_failed_at TIMESTAMPTZ, locked_until TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_login_at TIMESTAMPTZ
);
CREATE VIEW c4.users_public AS SELECT user_id, tenant_id, email, role, display_name, house_ids, is_active, created_at, last_login_at FROM c4.users;
CREATE TABLE c4.house_service_settings (
  house_id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES c4.tenants(tenant_id),
  enabled_services TEXT[] NOT NULL,
  quiet_start TIME, quiet_end TIME,                    -- house local time; both or neither
  sensitivity VARCHAR(6) NOT NULL DEFAULT 'medium' CHECK (sensitivity IN ('low','medium','high')),
  updated_by UUID NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK ((quiet_start IS NULL) = (quiet_end IS NULL))
);
CREATE TABLE c4.emergency_contacts (
  contact_id UUID PRIMARY KEY, house_id UUID NOT NULL, tenant_id UUID NOT NULL,
  name VARCHAR(80) NOT NULL, email VARCHAR(254) NOT NULL, phone VARCHAR(20),
  contact_type VARCHAR(20) NOT NULL CHECK (contact_type IN ('family','caregiver','neighbor','emergency_service')),
  priority SMALLINT NOT NULL CHECK (priority BETWEEN 1 AND 5),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (house_id, email),
  CONSTRAINT ux_contact_priority UNIQUE (house_id, priority) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE c4.service_clients (
  client_id VARCHAR(40) PRIMARY KEY, secret_hash VARCHAR(100) NOT NULL, scopes TEXT[] NOT NULL, is_active BOOLEAN NOT NULL DEFAULT true
);
CREATE TABLE c4.revoked_tokens (jti UUID PRIMARY KEY, expires_at TIMESTAMPTZ NOT NULL);
```
Grants: migration `0002_reader_grants` gives `c2_reader` SELECT on house_service_settings and emergency_contacts only, and `c3_reader` everything except `password_hash`/`secret_hash` (`users_public` instead of `users`; `service_clients` without `secret_hash`). `init.sql` sets no default privileges on c4, so a new table needs its own GRANT in its migration.
MongoDB `dashboard_stats_daily`: `{_id:"<house_id>:<yyyy-mm-dd>", tenant_id, house_id, date,
alerts_by_severity:{critical,high,medium,low}, alerts_by_type:{...}, detections_by_label:{...},
clips, feeds_active, generated_at}`; index `{tenant_id:1, date:-1}`, `{house_id:1, date:-1}`.

Keys: RSA 2048 private key PEM from Secrets Manager `homeai/jwt-signing-key` (JSON `{"current":{"kid","pem"},"previous":{...}?}`);
JWKS publishes current + previous.

---
## 3. API (under `/api/v1` unless noted)
| Method & path | Access | Request | Response / rules |
|---|---|---|---|
| `POST /auth/login` | public, 20/min/IP | `{email, password}` | 200 `{token, expires_in:3600, landing, claims}`; 401 `invalid_credentials` (same for unknown email/wrong password/inactive); 423 `account_locked` `{retry_after}`; 5 failures within 15 min → lock 15 min |
| `POST /auth/logout` | user | — | add `jti` to `revoked_tokens`; 204 |
| `GET /auth/me` | user | — | user (no hash) + houses `[ {house_id, name} ]` (names via `c1.houses`) |
| `POST /auth/service-token` | client credentials | `{client_id, client_secret, scope[]}` | 200 `{token, expires_in:900}`; 401 bad secret; 403 scope not allowed |
| `GET /auth/revoked` | any service token | `since` | `[jti...]` (non-expired) |
| `GET /.well-known/jwks.json` (root) | public | — | JWKS |
| `GET /dashboard/summary` | all roles (scoped) | `house_id?`, `range=24h|7d|30d`, `tenant_id?` (CS) | §4.3 shape |
| `GET /houses/{house_id}/settings` | O (own), CS | — | settings or defaults `{enabled_services: all 7, quiet: null, sensitivity: medium, is_default:true}` |
| `PUT /houses/{house_id}/settings` | O (own), CS | `{enabled_services[], quiet_start?, quiet_end?, sensitivity}` | upsert; 422 unknown service / one quiet time / bad format |
| `GET /houses/{house_id}/emergency-contacts` | O, CS | — | ordered by priority |
| `POST /houses/{house_id}/emergency-contacts` | O, CS | `{name, email, phone?, contact_type, priority?}` | 201; 409 `contact_limit` (5), `email_exists`; priority default last+1; inserting at an existing priority shifts others down |
| `PUT /houses/{house_id}/emergency-contacts/order` | O, CS | `{contact_ids[]}` | must list all exactly once (422); priorities 1..n in one tx; 204 |
| `PATCH /emergency-contacts/{id}` | O, CS | any field except house | 200 |
| `DELETE /emergency-contacts/{id}` | O, CS | — | 204; remaining priorities compacted |
| `GET /tenants` / `POST /tenants` | CS | `{name, timezone}` | list / 201 (then calls C2 `POST /alert-rules/defaults` for the new tenant, **forwarding the caller's cloud_staff bearer token**; best effort, failure only logged) |
| `GET /tenants/{id}/users` / `POST /tenants/{id}/users` | CS | `{email, password, role, display_name?, house_ids[]}` | 201; houses must exist in that tenant (`c1.houses`); password ≥ 10 chars with letters and digits |
| `PATCH /users/{id}` | CS | `{role?, house_ids?, is_active?, unlock?:true, password?}` | 200; never returns hash |
Owner check helper: `house_id in principal.house_ids` (403 otherwise); CS bypass.

---
## 4. Business logic
### 4.1 Login and lockout
```text
user = users.by_email(lower(email))
if user and user.locked_until > now: 423 (retry_after)
if not user or not user.is_active or not bcrypt.verify(pw, user.password_hash):
    if user: if first_failed_at older than 15 min: reset counter; failed_attempts += 1; if failed_attempts >= 5: locked_until = now + 15 min
    401 invalid_credentials            # constant-time: verify against a dummy hash when user missing
reset counters; last_login_at = now; token = issue_user(user); landing by role
```
### 4.2 Tokens
Claims per contracts §2.2/2.3; `jti=uuid4`; `kid` header; PyJWT RS256. Service clients verified with
bcrypt on `secret_hash`; requested scopes must be ⊆ allowed. Purge `revoked_tokens` past `expires_at` hourly.

### 4.3 Dashboard summary
```json
{ "kpis": {"houses": 128, "feeds_total": 420, "feeds_active": 412, "feeds_online": 400, "alerts": 57, "open_alerts": 5, "clips_classified": 9340},
  "alerts_by_severity": {"critical":6,"high":14,"medium":21,"low":16},
  "alerts_by_day": [{"date":"2026-10-25","count":7}],
  "detections_top": [{"label":"speech","count":3100}],
  "recent_alerts": [ {alert_id, alert_type_code, severity, status, house_name, room_name, triggered_at} ],
  "activity": [{"house_id","room_id","anomaly_score","band"}]       // owners only
}
```
Composition: past full days from `dashboard_stats_daily` (scope filter); **today** live via C1 `GET /feeds/stats`,
C2 `GET /alerts/stats` (`from=today 00:00 UTC`), C3 `GET /detections/stats`, recent alerts from C2 `GET /alerts?page_size=5`,
activity from C3. Calls run concurrently (httpx async or threads), 3 s timeout each; a failed source returns
zeros and `meta.unavailable:["c3"]` so the page still renders. `meta: {range, generated_at, live_since}`.
### 4.4 StatsRollupJob (00:15 UTC; also `POST /dashboard/rollup?date=` CS-only for demos)
For each house (from `c1.houses`): yesterday's counts from C2 stats (`group_by=severity`, `alert_type`),
C3 stats (`group_by=top_label`), clip count (C3 records clips total), feeds active (C1 stats) → upsert doc. Idempotent.
### 4.5 Settings and contacts validation
- `enabled_services ⊆ {fire_safety, distress, intrusion, fall, wellness, presence, pet}`; quiet times `HH:MM`, may wrap midnight; both or neither.
- Contacts: ≤ 5, valid email (pydantic `EmailStr`), unique per house, priority 1..5; reorder lists all ids.
- Note shown in UI and API docs: critical and high alerts always bypass quiet hours; sensitivity low/medium/high = +0.10/0/−0.10 on rule thresholds (applied by C2).

---
## 5. Code structure
```
app/api/{auth.py, jwks.py, service_tokens.py, dashboard.py, settings.py, contacts.py, tenants.py, users.py, health.py}
app/services/{auth_service.py, password_hasher.py, jwt_issuer.py, token_denylist.py, dashboard_service.py, stats_aggregator.py, settings_service.py, contact_service.py, tenant_user_service.py}
app/repositories/{user_repo.py, tenant_repo.py, settings_repo.py, contact_repo.py, service_client_repo.py, revoked_repo.py, stats_repo.py}
app/gateways/{c1_client.py, c2_client.py, c3_client.py, house_reader.py, secrets_gateway.py}
app/jobs/{stats_rollup.py, revoked_purge.py}
libs/homeai_common/auth.py, service_client.py, testing.py   # shared, owned by C4
web/src/{auth/, shared/, App.tsx}                            # shell and kit, owned by C4
```

---
## 6. UI
| Page | Key elements | API |
|---|---|---|
| **Login** `/login` | email, password, error states (401, 423 with countdown), redirect to landing | `POST /auth/login` |
| **App shell** | Sidebar by role, header with house picker (owners) and user menu (logout), breadcrumb, toasts, RouteGuard (wrong role → own landing; 401 → login) | `/auth/me`, `/auth/logout` |
| **Home Overview** `/home/overview` | KPI tiles (open alerts, feeds online/total, clips today, detections today), open alerts list (C2, poll 15 s, critical banner), feed status list (C1), activity widget with anomaly band (C3), links to Settings and Alerts | `/dashboard/summary?house_id=` + C2/C1/C3 widgets |
| **Services and Settings** `/home/settings` | ToggleTable (7 services with the alert types they allow), quiet hours from/to (house time zone shown), sensitivity segmented control with explanation, Emergency contacts SortableList (drag + up/down buttons, add/edit/delete, 5 max), SaveBar with unsaved count; 422 inline | settings + contacts endpoints |
| **System Dashboard** `/ops/dashboard` | FilterBar (tenant, house, range), KPI tiles, Alerts by severity (bar), Alerts by day (line), Detections by label (horizontal bar), Recent alerts table, "unavailable" badges per source | `/dashboard/summary` |
| **Tenants and Users** `/ops/tenants` | Tenants table + create; users table per tenant (role, houses, active, locked) + create/edit drawer (house multi-select from C1 houses), unlock, deactivate | tenants/users endpoints, C1 `GET /houses?tenant_id=` |
Shared kit (§4 of `04_FRONTEND.md`) is built by C4 in week 1–2 so others can use it.

---
## 7. Tests
Unit: password hashing/verify; lockout counter window; claims builder; JWKS output; scope subset check;
settings validator (wrap-around quiet hours, both-or-neither); contacts reorder/compaction; summary merge
with a failing source.
API: login 200/401/423; token verifies via `homeai_common.auth` against the live JWKS; logout → `/auth/revoked`
contains jti; service token scopes; owner cannot read other house settings (403); contact limit 409; email
exists 409; reorder 422 when ids incomplete; tenants/users CS-only (403 for others); create user with house of
another tenant → 422; summary with mocked C1/C2/C3 clients; rollup idempotent.
Web: RouteGuard redirects, AuthProvider 401 handling, SortableList keyboard reorder.

---
## 8. Task list
| ID | Task | Depends |
|---|---|---|
| C4-01 | Skeleton, settings, health, Alembic, Dockerfile (P0-6) | P0-3 |
| C4-02 | Migration (§2), key loading from Secrets Manager/LocalStack, JWKS endpoint | C4-01 |
| C4-03 | Login + lockout + `/auth/me` + logout + `/auth/revoked` (**P0-7**) | C4-02 |
| C4-04 | Service clients + `POST /auth/service-token` (**P0-7**) | C4-02 |
| C4-05 | `homeai_common.auth` + `service_client` + `testing` (**P0-4**) | C4-02 |
| C4-06 | Settings + contacts APIs with validation and owner checks | C4-03 |
| C4-07 | Tenants + users admin APIs (calls C2 defaults best-effort) | C4-03 |
| C4-08 | C1/C2/C3 read clients + StatsAggregator + `GET /dashboard/summary` | C4-04 |
| C4-09 | StatsRollupJob + revoked purge + rollup endpoint | C4-08 |
| C4-10 | Web shell: AuthProvider, Login, RouteGuard, AppShell, house picker, API client (**P0-8**) | P0-2 |
| C4-11 | Shared UI kit (DataTable, FilterBar, StatusChip, SeverityBadge, KpiTile, ChartCard, FormPanel, ActionBar, SaveBar, SortableList, ClipPlayer, ConfidenceBars, Timeline, ConfirmDialog, Toasts) with Vitest | C4-10 |
| C4-12 | UI: Services and Settings (+ contacts) | C4-06, C4-11 |
| C4-13 | UI: Home Overview, System Dashboard | C4-08, C4-11 |
| C4-14 | UI: Tenants and Users | C4-07 |
| C4-15 | Seed: tenants, users, settings, contacts, service clients | C4-06 |
| C4-16 | AWS setup lead (03 §8): EC2, RDS, S3, secrets, IAM, Caddy TLS | week 3 |
| C4-17 | Playwright `e2e/c4-login-settings.spec.ts`, demo prep, video | all |

## 9. Acceptance checklist
- [ ] Every other service verifies C4 tokens through JWKS; service tokens work for C3→C2, C2→C1, C4→C1/C2/C3.
- [ ] Lockout, logout revocation and role landing work; wrong-role routes redirect.
- [ ] Settings/contacts validated; C2 picks up quiet hours, sensitivity and contact order (integration I-3).
- [ ] Dashboards render with partial data when a source is down.
- [ ] Shared UI kit used by all four feature folders; accessible (keyboard, icon + word).

---
## 10. Deliverable #3 demo (C4)
### 10.1 Live demo (≈ 7 min)
1. Log in as each role → three different landing pages; owner opens `/ops/dashboard` → redirected.
2. Wrong password 5× → `account_locked` with countdown; unlock as `ops@homeai.test` in Tenants and Users.
3. Show JWKS and decode the token claims (role, tenant, house_ids, exp) in the UI's "token info" dev panel (DEMO_MODE) or jwt.io.
4. **Services and Settings** as Maple owner: turn off wellness, set quiet hours 22:00–07:00, sensitivity high; add a 4th contact, try a duplicate email (409), reorder contacts by drag and by keyboard, save.
5. Show the effect in C2 (with C2 running): a low-severity cough during quiet hours is held; a high alert still emails contacts in the new order.
6. **System Dashboard** as ops: filter by tenant/house/range; charts and recent alerts; stop c3 container → "C3 unavailable" badge while other tiles still work.
7. **Tenants and Users**: create tenant "Demo Homes", create an owner user with a house → log in as them.
8. Logout → reuse the old token in Swagger → 401 `token_revoked`. Service token via `POST /auth/service-token`.
9. Unit demo: `make test-c4`, web tests, Swagger `/api/v1/docs/c4`.
### 10.2 Scenario video (≈ 5 min) — "A family member sets up their parent's home"
Owner signs in → Home Overview → configures services, quiet hours, sensitivity → adds and orders emergency
contacts → sees an alert appear on Home Overview and the dashboard update; ops staff view the System Dashboard
across houses.
### 10.3 Prep
Seed users with known passwords, a second tenant for isolation, rollup run for the last 7 days
(`POST /dashboard/rollup` for backfill with seeded alerts/detections), confirm C2 subscriptions for demo contacts.
