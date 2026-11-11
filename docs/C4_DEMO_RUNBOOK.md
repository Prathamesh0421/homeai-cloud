# C4 demo runbook — System Dashboard / Auth (Mohit)

The script is the C4 plan §10.1; this page is how to run it on the EC2 demo host, step by step.
Rubric (06 §4): every C4 function through the UI, backend proof, edge cases, unit tests, on EC2.

**URL** http://44.226.166.194 · **Swagger** http://44.226.166.194/api/v1/docs/c4 · **JWKS** http://44.226.166.194/.well-known/jwks.json
**Logins** (password `Demo!2026`):
| Email | Role | Lands on |
|---|---|---|
| `ops@homeai.test` | cloud_staff | System dashboard (`/ops/dashboard`) |
| `owner.maple@acme.test` | house_owner (Maple) | Home overview (`/home/overview`) |
| `iot@acme.test` | iot_staff | Camera feeds (`/iot/feeds`) |
| `owner.oak@acme.test` | house_owner (Oak) | isolation check |
| `owner.sun@sunrise.test` | house_owner (other tenant) | lockout practice account |

Commands marked **EC2** run on the host from the laptop, e.g.
`ssh homeai-ec2 'cd ~/homeai-cloud && docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml ps'`.

**Nobody redeploys during rehearsal or the demo.** Agree a quiet window with the team (C2 notes the
same: a mid-handoff rebuild can leave detections pending).

## 1. Before (day before, then 1 hour before)
| | Step | How |
|---|---|---|
| ☐ | Instance running, all 7 containers up | Console → EC2 → Start; then **EC2** `docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml --profile gateway --profile c3 --profile c1 up -d` |
| ☐ | C4 healthy | `curl http://44.226.166.194/api/v1/health/c4` → `"status":"ok"` |
| ☐ | Seed users exist | Login works for the five emails above with `Demo!2026` |
| ☐ | Maple settings sane | Services & settings (Maple): wellness **on**, quiet hours `22:00–07:00`, sensitivity **medium**, 3 contacts (Alice → Bob → Carol). If you changed them in rehearsal, put them back |
| ☐ | C2 SNS ready (for settings → alert effect) | SNS: Maple topic has 3 confirmed subscriptions (same as C2 runbook §1) |
| ☐ | Demo clips on laptop (optional quiet-hours step) | `demo_clips/cough.wav` and `glass_break.wav` (or use C2’s `make demo-c2-detect` fallback) |
| ☐ | Tests green | laptop `make test-c4` |
| ☐ | Tabs open | 1 private: login · 2 ops → System dashboard · 3 Maple owner → Home overview / Settings · 4 Swagger C4 · 5 terminal (EC2) · 6 jwt.io |
| ☐ | Browser zoom 110%; passwords on a sticky note (not in slides) | |
| ☐ | Rehearsed twice | this page, top to bottom |

## 2. Live demo (~7–8 min; timings from 06 §4.1)

**0:00–0:30 · Where C4 sits.** Login / JWT / RBAC, tenants & users, house services & emergency
contacts, Home Overview and System Dashboard. C4 owns schema `c4` and the JWKS key; everyone else
*verifies* C4 tokens. Cross-component reads go through APIs or reader roles — C4 never writes C1/C2/C3 data.

**0:30–1:30 · Role landings and route guards.**
1. Log in as `ops@homeai.test` → **System dashboard**. Point at the app shell (ops nav).
2. Log out → `iot@acme.test` → **Camera Feed Manager** (`/iot/feeds`).
3. Log out → `owner.maple@acme.test` → **Home overview** (KPIs, open alerts, feeds). Paste
   `/ops/dashboard` in the address bar → redirected to `/home/overview` (wrong-role guard).

**1:30–2:30 · Lockout and unlock.**
4. Private window: as `owner.sun@sunrise.test`, enter a wrong password **5 times** → login shows
   locked with a countdown (`423 account_locked`). Do **not** lock `ops@` or Maple.
5. As `ops@homeai.test` → **Tenants & users** → open the Sunrise tenant → user row → **Unlock** →
   confirm. Private window: correct password works again.

**2:30–3:15 · JWT / JWKS.**
6. After a fresh Maple login, copy the bearer token (DevTools → Application → Session Storage
   `homeai.token`, or Network → any `/api/v1/...` → Authorization header).
7. Tab: open http://44.226.166.194/.well-known/jwks.json (one public key). Paste the JWT into
   [jwt.io](https://jwt.io) → show claims: `role`, `tenant_id`, `house_ids`, `exp`, `iss`.
   (No in-app “token info” panel; JWKS + jwt.io is the plan’s fallback.)

**3:15–4:45 · Services & settings + contacts (Maple owner).**
8. `owner.maple@acme.test` → **Services & settings**.
9. Turn **Wellness** off → set quiet hours `22:00`–`07:00` (or leave them) → sensitivity **High** → Save.
10. **Emergency contacts**: **Add** a 4th contact (your own email, type *neighbor*) → Save. Try the
    same email again → toast / `409` duplicate. Reorder Alice/Bob/Carol (drag **and** keyboard) → Save.
11. *(With C2 up, ~45 s)* Show the effect: quiet hours covering now + low cough held; high glass-break
    still alerts and emails in the new order. Fast path:
    - **EC2** `make demo-c2-quiet-hours ARGS=--cover-now`
    - Upload `cough.wav` to Maple Kitchen Mic **or** **EC2** `make demo-c2-detect ARGS="--label cough --conf 0.80"` → `no_alert` / `quiet_hours`
    - Upload `glass_break.wav` **or** `make demo-c2-detect ARGS="--label glass_break --conf 0.80"` → alert + emails
    - If time is short, skip the live trigger and say “C2 evaluates against these settings” and move on.

**4:45–5:45 · System dashboard + partial failure.**
12. `ops@homeai.test` → **System dashboard**: filter tenant **Acme** / house **Maple** / range **24h**
    (or 7d). Point at KPI tiles, charts, recent alerts.
13. **EC2** `docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml stop c3-data`
    → refresh / wait → warning that **C3** is unreachable; other tiles still work. Then
    **EC2** `… start c3-data` (and `c3-worker` if it stopped) before the next presenter’s turn.

**5:45–6:30 · Tenants & users.**
14. **Tenants & users** → **Create tenant** “Demo Homes” (timezone e.g. `America/Los_Angeles`).
15. Open it → **Add user**: email `owner.demo@demo.test`, password ≥ 10 chars, role `house_owner`,
    assign a house if the picker lists one (seed houses / C1). Create → private window login → lands
    on Home overview. (If house assign is empty, still show create + login; isolation is the point.)

**6:30–7:00 · Logout revocation + service token.**
16. Maple owner: **Logout**. In Swagger C4, Authorize with the **old** bearer → `GET /auth/me` →
    `401` (`token_revoked` / unauthorized).
17. Swagger: `POST /auth/service-token` with a configured client
    (`client_id` / `client_secret` from the host `.env`, e.g. `c2-alerts`) → 200 with a short-lived
    service JWT. Optionally `GET /auth/me` with it → `403` (service tokens cannot call `/auth/me`).

**7:00–7:30 · Tests and deployment.**
18. Laptop: `make test-c4` (green). Swagger `/api/v1/docs/c4`.
19. **EC2** `docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml --profile gateway --profile c3 --profile c1 ps`.

**After.** Restore Maple settings (wellness on, quiet hours `22:00–07:00`, sensitivity medium, remove
the 4th contact if it was yours). **EC2** `make demo-c2-quiet-hours ARGS="--set 22:00-07:00"` if you
used `--cover-now`. Leave `c3-data` / `c3-worker` running.

## 3. If something goes wrong
| Problem | Do |
|---|---|
| Locked yourself out of ops | Wait out the countdown, or unlock from another ops session / DB; prefer locking `owner.sun` only |
| Settings save fails | Check house selected at top of Services & settings; 403 = wrong role |
| Duplicate contact no 409 | Same email + same house already exists — use a fresh address |
| Dashboard empty KPIs | Rollup may be cold: Swagger as ops `POST /dashboard/rollup?date=YYYY-MM-DD` for a few recent days (C4-09); or show live open-alert tiles from C2 |
| “C3 unreachable” won’t clear | `docker compose … start c3-data c3-worker`; wait health; Retry on the banner |
| Service-token 401 | Wrong secret in Swagger vs host `.env` (`SERVICE_CLIENT_SECRET_*`) |
| Site down | Console → instance running? Then the `up -d` command from §1 |
| C2 step fails | Skip the live quiet-hours proof; C4 still owns settings UI + RBAC + dashboard |

## 4. Scenario video (~5 min, C4 plan §10.2 “A family member sets up their parent's home”)
Title card (10 s) → Maple owner signs in → Home Overview → Services & settings (toggles, quiet hours,
sensitivity) → add and reorder emergency contacts → an alert appears on Home Overview / Alerts →
cut to ops on System Dashboard across houses → show EC2 URL once and one backend view (JWKS or
Swagger). Record twice, keep the better take; ≤ 7 min, MP4.

## 5. Hand-off with Prathamesh (C2)
C4 demo shows **settings + contacts**; C2 demo shows **rules → alert → SNS → Alert View**.
Agree order so quiet hours / sensitivity are left in a known state for whoever goes second.
Use [`docs/C2_DEMO_RUNBOOK.md`](C2_DEMO_RUNBOOK.md) for his script; do not redeploy between your slots.
