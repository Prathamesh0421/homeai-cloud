# 05 — Integration and testing

## 1. Test pyramid
| Level | Where | Runs | Owner |
|---|---|---|---|
| Unit (pure logic, no I/O) | `services/<cx>/tests/unit` | every PR (CI) | component owner |
| API (FastAPI TestClient + real Postgres/Mongo/LocalStack) | `services/<cx>/tests/api` | every PR (CI services) | component owner |
| Contract (shared Pydantic models) | `libs/homeai_common/tests/test_contracts.py` + producer/consumer tests | every PR | producer owns the model |
| Integration (running stack, several services) | `tests/integration/` (repo root) | `make test-integration`, nightly + before demos | pairs listed below |
| E2E UI (Playwright) | `web/e2e/` | before demos (rehearsal + video) | component owner |
| Performance (final project) | `scripts/perf/` | final project | C3 + C2 |

Pytest markers: `unit`, `api`, `integration`, `slow` (real YAMNet), `aws` (needs real AWS). CI runs `unit` + `api` (+ contracts).
Coverage gate: ≥ 70% per service overall, ≥ 80% for `app/services/`.

## 2. Contracts in code
`libs/homeai_common/contracts.py` holds Pydantic models for every cross-component payload in `02_CONTRACTS.md` §4:
`MediaEventDoc`, `DetectionDoc`, `EvaluateRequest`, `EvaluateResponse`, `PlaybackUrlResponse`, `FeedStats`,
`StatBucket`, `ServiceTokenRequest/Response`. Producers serialise with them; consumers parse with them.
Changing one requires both owners' review (CODEOWNERS on that file: all four members).
Contract tests: each model has a fixture JSON in `libs/homeai_common/tests/fixtures/` copied from the docs;
the test loads the fixture into the model and dumps it back unchanged.

## 3. Test data
- `scripts/seed.py` (fixed UUIDs, see `03` §7) is used by integration tests, E2E and demos.
- `make reset-demo`: truncates dynamic tables/collections (alerts, history, notifications, media_events,
  ai_detections, activity_patterns, dashboard_stats_daily, integrity_reports) and reseeds. Never touches users/tenants.
- Unit/API tests create their own data with factories (`tests/factories.py` per service); each test runs in a
  transaction rolled back at the end; Mongo tests use a per-test database name.

## 4. Integration tests (`tests/integration/`, stack running via `make up && make seed`)
| ID | Flow | Pass criteria | Pair |
|---|---|---|---|
| I-1 | C1 → C3: upload `glass_break.wav` to Maple Kitchen Mic | within 30 s `media_events.status=analyzed`, detection exists with `top_label=glass_break` | Ekant + Renuka |
| I-2 | C3 → C2: detection from I-1 | exactly one alert (`intrusion`, high); re-POST evaluate → `duplicate:true` | Renuka + Prathamesh |
| I-3 | C4 settings → C2: set quiet hours covering now, upload `cough.wav` then `glass_break.wav` | cough → `no_alert quiet_hours`; glass → alert; with sensitivity `high` a 0.50 cough now alerts outside quiet hours; emails (log notifier) in contact priority order after reorder | Mohit + Prathamesh |
| I-4 | C2 → C1: `GET /alerts/{id}` and alert view | `clip_url` downloads the S3 object | Prathamesh + Ekant |
| I-5 | C4 ← C1/C2/C3: `GET /dashboard/summary` | KPIs equal counts computed directly from the stores; stopping c3 → `meta.unavailable` contains `c3` | Mohit + all |
| I-6 | Tenant isolation: Sunrise owner token against every list endpoint of C1–C4 | never sees Acme rows; direct id access → 404/403 | all |
| I-7 | Revocation: logout, then call C1/C2/C3 with the old token | 401 within 60 s | Mohit |
| I-8 | Worker scale: 2 workers, 20 clips via `device_sim.py` | 20 detections, 20 distinct media ids, no duplicates, 0 failed | Renuka |

## 5. End-to-end scenario (final project acceptance, also the group demo)
**E2E-1 "Night-time intrusion at Maple St"**
1. ops creates tenant rule tweaks; owner sets quiet hours 22:00–07:00 and contacts.
2. device simulator uploads `glass_break.wav` to Maple Living feed (C1).
3. C3 classifies → `glass_break 0.78` → C2 raises `intrusion` (high, bypasses quiet hours).
4. SNS emails contact #1 then #2 with signed links; contact opens the public Alert View.
5. Owner sees the alert on Home Overview (≤ 15 s), opens Alert Detail, plays the clip, acknowledges, resolves.
6. System Dashboard shows the alert in today's counts and in recent alerts; Records show the detection; Data Dictionary and Integrity are clean.
Automated as `tests/integration/test_e2e_intrusion.py` (log notifier) and `web/e2e/e2e-intrusion.spec.ts`.

## 6. Playwright specs (demo rehearsals; `video: 'on'` to preview recordings)
| Spec | Covers |
|---|---|
| `c1-feed-setup.spec.ts` | house/room → add feed → 409 room_required → enable → config v2 → upload → clip listed |
| `c2-alert-lifecycle.spec.ts` | alert appears → detail → acknowledge → resolve; rule create + duplicate 409; public view + expired |
| `c3-model-activate.spec.ts` | test classify → new version → edit label map → evaluate → activate → deployment panel shows version → rollback |
| `c4-login-settings.spec.ts` | role landings → guard redirect → lockout → settings + contacts reorder → dashboard filters |
| `e2e-intrusion.spec.ts` | E2E-1 UI steps |

## 7. Performance and scaling (final project; closes TBD-3 and TBD-5)
- `scripts/perf/clip_to_alert.py --clips 100 --rate 2/s`: uploads clips, polls C2 until each alert/no_alert,
  writes CSV of `upload→queued`, `queued→analyzed`, `analyzed→decision`, `decision→email sent`.
- Report p50/p95 per stage with 1 and 2 workers on `t3.large`; record results in `docs/RESULTS.md`.
- Targets from D2: `/alerts/evaluate` p95 < 500 ms; clip-to-handoff p95 < 5 s at 1 clip/s.

## 8. Definition of "integrated"
A feature is integrated when its I-test passes against the stack on EC2 (not only locally), its Playwright
spec passes, and the owners of both sides have ticked it in their acceptance checklists.
