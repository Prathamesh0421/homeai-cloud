# C2 — Alert Tracking and Monitor — Implementation Plan
**Owner:** Prathamesh Ravindra Sawant · **Service:** `services/c2_alerts` (port 8002) · **UI:** `web/src/features/c2-alerts`
**Reads first:** `AGENTS.md`, `docs/01`–`04`. Design reference: D2 Part II (C2).

## 0. Goal in one line
Evaluate every detection against alert rules and house settings, raise an alert exactly once, email emergency
contacts in priority order through SNS with a signed 24-hour link, and run the alert lifecycle
(acknowledge / resolve / false positive) with a full audit trail.

---
## 1. Scope
**In:** alert types (seeded), alert rules CRUD, `POST /alerts/evaluate` (rule engine), alerts list/detail/stats,
lifecycle actions, status history, notifications (in-app record + SNS email), retry job, SNS subscription sync
job **[D3 addition]**, signed alert view, C2 UI pages, demo helpers.
**Out:** classification (C3), settings/contacts storage (C4 — read-only to C2), clip storage (C1).

### 1.1 Dependencies
| Needs | From | Contract | Stub until ready |
|---|---|---|---|
| JWT verify, service tokens | C4 | 02 §2 | `homeai_common.testing` keys |
| House settings, contacts | C4 `c4.house_service_settings`, `c4.emergency_contacts` (read-only role) | 02 §4.5 | Seed rows from `make seed-c4` (C4-15, IDs in `scripts/seed_ids.py`); C2's default rules from `make seed-c2` |
| House timezone, room names | C1 `c1.houses`, `c1.rooms` (read-only) | 02 §4.5 | seed |
| Detections | C3 `ai_detections` (Mongo read-only) | 02 §4.2 | `scripts/demo/c2_fake_detection.py` (DEMO_MODE) |
| Playback URL | C1 `GET /clips/{id}/playback-url` (service `clips:playback`) | 02 §4.4 | return `null` url, UI shows "clip unavailable" |
| **Provides** | **To** | | |
| `POST /alerts/evaluate` | C3 | 02 §4.3 | |
| `GET /alerts/stats`, `GET /alerts?status=open` | C4 dashboards / Home Overview | 02 §4.6 | |

---
## 2. Data model — PostgreSQL schema `c2` (Alembic `0001_initial`, `0002_seed_alert_types`)
```sql
CREATE TABLE c2.alert_types (
  alert_type_id          SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                   VARCHAR(40) NOT NULL UNIQUE,
  name                   VARCHAR(80) NOT NULL,
  category               VARCHAR(10) NOT NULL CHECK (category IN ('emergency','safety','security','wellness','system')),
  service_code           VARCHAR(40) NOT NULL,
  trigger_label          VARCHAR(40) NOT NULL,
  default_severity       VARCHAR(8)  NOT NULL CHECK (default_severity IN ('critical','high','medium','low')),
  default_min_confidence NUMERIC(3,2) NOT NULL CHECK (default_min_confidence BETWEEN 0 AND 1)
);
CREATE TABLE c2.alert_rules (
  rule_id        UUID PRIMARY KEY,
  tenant_id      UUID NOT NULL,
  house_id       UUID,                                -- NULL = tenant-wide default
  alert_type_id  SMALLINT NOT NULL REFERENCES c2.alert_types(alert_type_id),
  trigger_labels TEXT[] NOT NULL CHECK (cardinality(trigger_labels) >= 1),
  min_confidence NUMERIC(3,2) NOT NULL CHECK (min_confidence BETWEEN 0 AND 1),
  room_id        UUID,
  severity       VARCHAR(8) CHECK (severity IN ('critical','high','medium','low')),
  is_enabled     BOOLEAN NOT NULL DEFAULT true,
  version        INT NOT NULL DEFAULT 1,
  created_by     UUID NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at     TIMESTAMPTZ
);
CREATE UNIQUE INDEX ux_rules_dup ON c2.alert_rules (tenant_id,
  COALESCE(house_id,'00000000-0000-0000-0000-000000000000'), alert_type_id,
  COALESCE(room_id,'00000000-0000-0000-0000-000000000000')) WHERE is_enabled AND deleted_at IS NULL;
CREATE INDEX ix_rules_eval ON c2.alert_rules (tenant_id, house_id) WHERE is_enabled AND deleted_at IS NULL;

CREATE TABLE c2.alerts (
  alert_id        UUID PRIMARY KEY,
  tenant_id       UUID NOT NULL,
  house_id        UUID NOT NULL,
  room_id         UUID,
  alert_type_id   SMALLINT NOT NULL REFERENCES c2.alert_types(alert_type_id),
  rule_id         UUID NOT NULL REFERENCES c2.alert_rules(rule_id),
  detection_id    UUID NOT NULL UNIQUE,                -- idempotency key
  threshold       NUMERIC(3,2),                        -- [D3, 0003] effective threshold at raise time
  media_id        UUID NOT NULL,
  top_label       VARCHAR(40) NOT NULL,
  top_confidence  NUMERIC(4,3) NOT NULL,
  severity        VARCHAR(8) NOT NULL CHECK (severity IN ('critical','high','medium','low')),
  status          VARCHAR(16) NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved','false_positive')),
  triggered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  acknowledged_at TIMESTAMPTZ, resolved_at TIMESTAMPTZ,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_alerts_list  ON c2.alerts (house_id, status, triggered_at DESC);
CREATE INDEX ix_alerts_stats ON c2.alerts (tenant_id, triggered_at);

CREATE TABLE c2.alert_status_history (
  history_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  alert_id    UUID NOT NULL REFERENCES c2.alerts(alert_id) ON DELETE RESTRICT,
  from_status VARCHAR(16), to_status VARCHAR(16) NOT NULL,
  actor_id    VARCHAR(64) NOT NULL,     -- user id or 'system'
  actor_role  VARCHAR(20) NOT NULL,
  note        TEXT,
  changed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_hist_alert ON c2.alert_status_history (alert_id, changed_at);

CREATE TABLE c2.notifications (
  notification_id UUID PRIMARY KEY,
  alert_id        UUID NOT NULL REFERENCES c2.alerts(alert_id),
  contact_id      UUID,                 -- NULL for in_app
  channel         VARCHAR(6) NOT NULL CHECK (channel IN ('in_app','email')),
  recipient       VARCHAR(254),
  priority        SMALLINT,
  status          VARCHAR(7) NOT NULL CHECK (status IN ('queued','sent','failed')),
  attempt_count   SMALLINT NOT NULL DEFAULT 0,
  sns_message_id  VARCHAR(100),
  last_error      TEXT,
  next_attempt_at TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at         TIMESTAMPTZ
);
CREATE INDEX ix_notif_retry ON c2.notifications (status, next_attempt_at) WHERE status = 'failed';
```
`0002_seed_alert_types` inserts the 7 alert types from `02_CONTRACTS.md` §3. Tenant default rules (one
per type, `house_id NULL`) are created by `scripts/seed.py` and by `POST /alert-rules/defaults` (body `{tenant_id}`)
**[D3 addition, cloud_staff]** for new tenants.

---
## 3. API (all under `/api/v1`)
Access: **O** = house_owner (own houses), **CS** = cloud_staff, **svc** = service scope.

| Method & path | Access | Request | Response / errors |
|---|---|---|---|
| `GET /alerts` | O, CS, svc `alerts:read` | `status` (csv), `severity`, `alert_type_code`, `house_id`, `tenant_id` (CS), `from`, `to`, `page`, `page_size` | list `{alert_id, house_id, house_name, room_id, room_name, alert_type_code, alert_type_name, severity, status, top_label, top_confidence, triggered_at}` |
| `GET /alerts/{id}` | O, CS | — | alert + `allowed_actions[]` **[D3]** + `evidence {detection_id, media_id, labels[], model, threshold, detection_available}` **[D3]** + `timeline[]` + `notifications[]` (+ `view_link` per email notification **only if `DEMO_MODE=1`**); 404/403 |
| `GET /alerts/stats` | O, CS, svc `alerts:read` | `group_by` (`alert_type`/`severity`/`house`/`day`), `from`, `to` (required, ≤ 366 days), `house_id`, `status`, `tenant_id` | `[{key, count}]` |
| `POST /alerts/{id}/acknowledge` | O, CS | `{note?}` ≤ 500 | 200 alert; 409 `invalid_state` |
| `POST /alerts/{id}/resolve` | O, CS | `{note?}` | 200; 409 |
| `POST /alerts/{id}/false-positive` | O, CS | `{reason}` 1–500 required | 200; 422 missing reason; 409 |
| `POST /alerts/evaluate` | svc `alerts:evaluate` | contract 02 §4.3 | 201 / 200 / 503 |
| `GET /alert-types` | O, CS | — | list incl. defaults and service code |
| `GET /alert-rules` | CS | `tenant_id`, `house_id`, `alert_type_code`, `is_enabled`, page | list incl. `false_positive_count_30d` |
| `POST /alert-rules` | CS | `{tenant_id?, house_id?, alert_type_code, trigger_labels[], min_confidence?, room_id?, severity?, is_enabled}` | 201 + `Location`; 422; 409 `duplicate_rule` |
| `GET /alert-rules/{id}` **[D3]** | CS | — | rule + `ETag: "<version>"`; 404 (target of `POST`'s `Location`) |
| `PUT /alert-rules/{id}` | CS | editable fields; header `If-Match: <version>` | 200 + new `ETag`; 412 `version_mismatch` `{current_version}`; 409 `duplicate_rule` when re-enabling into a duplicate |
| `DELETE /alert-rules/{id}` | CS | — | soft delete, 204 |
| `POST /alert-rules/defaults` **[D3]** | CS | `{tenant_id}` | creates missing tenant default rules; 200 `{created: n}` |
| `POST /alert-rules/subscriptions/sync` **[D3]** | CS | `{house_id?}` | runs subscription sync now; `{topics, subscribed, pending, removed, failed}` (`failed` = houses skipped because SNS failed); 409 `sync_in_progress` while the 5-minute job runs; 503 if C4 contacts are unavailable |
| `GET /alert-view/{token}` | public, rate-limited 60/min/IP | — | read-only view (below); 401 `token_expired`; 404 |
Alert-view body: `{alert_type_name, severity, status, house_name, room_name, triggered_at, labels[], clip_url, expires_at}` — no owner/contact PII.
Rule validation: `alert_type_code` exists; `trigger_labels` ⊆ the 7 home labels; `0 ≤ min_confidence ≤ 1`
(default = type default); `room_id` belongs to `house_id` (check `c1.rooms`); CS must give `tenant_id` when
`house_id` is null (else derive from `c1.houses`).

---
## 4. Business logic
### 4.1 `RuleEngine.evaluate(req)` (service-token endpoint)
```text
1  existing = alerts.find_by_detection(req.detection_id) -> return 200 duplicate
2  d = detection_gateway.get(req.detection_id)  (Mongo, read-only) ; if missing or d.house_id != req.house_id -> 422
3  house = c1_reader.house(req.house_id) (timezone, tenant) ; settings = c4_reader.settings(house_id) or DEFAULTS
4  rules = rules_repo.enabled_for(tenant, house, d.room_id):
       per alert type the most specific applicable enabled rules win: rule for this room >
       whole-house rule > tenant default (rules for other rooms stay, for room_mismatch, but hide
       nothing; disabled rules hide nothing); order by severity rank desc, room-specific first,
       created_at asc
5  best_miss = "no_rule_match"
6  for rule in rules:
       t = rule.alert_type
       if d.top_label not in rule.trigger_labels: continue          # label first (CHANGELOG 2026-11-03)
       if t.service_code not in settings.enabled_services: best_miss = max(best_miss,"service_disabled"); continue
       thr = round(clamp(rule.min_confidence + SENS[settings.sensitivity], 0.05, 0.95), 2)   # low +0.10, medium 0, high -0.10
       if d.top_confidence < thr: best_miss = max(best_miss,"below_threshold"); continue
       if rule.room_id and rule.room_id != d.room_id: best_miss = max(best_miss,"room_mismatch"); continue
       sev = rule.severity or t.default_severity
       if in_quiet_hours(now, house.timezone, settings) and sev in ("medium","low"): return no_alert("quiet_hours")
       alert = lifecycle.raise_alert(rule, d, sev)      # tx: insert alert + history(null->open, system)
       notification_service.notify(alert)               # after commit
       return 201 alert
7  return 200 no_alert(best_miss)    # reason precedence: room_mismatch > below_threshold > service_disabled > no_rule_match
```
- Race safety: catch `UniqueViolation` on `detection_id` → re-read and return duplicate.
- `in_quiet_hours`: convert now to house timezone; window may wrap midnight (22:00–07:00).
- Log every decision (JSON: detection_id, decision, reason, rule_id, threshold).

### 4.2 Lifecycle (`AlertLifecycleService.transition`)
Allowed: `open→acknowledged`, `acknowledged→resolved`, `open|acknowledged→false_positive`. Steps: load alert
(404), `assert_house` (403), validate reason for false positive (422), check allowed (409 with
`details {from,to}`), `UPDATE ... SET status=:to WHERE alert_id=:id AND status=:from` → 0 rows → 409,
set `acknowledged_at`/`resolved_at`, append history with actor id, role, note. One transaction.

### 4.3 Notifications (`NotificationService.notify`)
1. Always insert `in_app` notification `status=sent` (the SPA polls `GET /alerts`).
2. If severity ∈ {critical, high}: contacts = `c4_reader.contacts(house)` ordered by priority. For each:
   a. `sns.ensure_topic("homeai-house-<house_id>")`; `sns.ensure_subscription(topic, email, filter={"contact_id":[id]})`.
   b. Insert notification `queued` with recipient + priority.
   c. If subscription is `PendingConfirmation` → mark `failed`, `last_error="subscription_pending"`, `next_attempt_at=+1 min`.
   d. Else build link `PUBLIC_BASE_URL/alert-view/<token>` (token §4.4), publish with `MessageAttributes
      {contact_id, alert_id, severity}` → `sent` + `sns_message_id`; on error → `failed`, attempt 1, next +1 min.
3. `NOTIFIER=log` (local): same flow but writes the email (subject, body, link) to the log and marks `sent`.
Email subject: `[HomeAI] CRITICAL Smoke alarm - Maple St` (ASCII: SNS rejects non-ASCII subjects; CHANGELOG 2026-11-03); body: room, time (UTC + house local), label +
confidence, link, link expiry, "If someone is in danger call 911".

### 4.4 Signed link (`SignedLinkService`)
`payload = base64url(json({"aid","cid","exp","kid"}))`; `sig = base64url(HMAC_SHA256(key[kid], payload))`;
token = `payload.sig`; `exp = triggered_at + 24h`. Verify: split (404), decode (404), constant-time compare
(404), `now > exp` (401 `token_expired`), alert exists (404). Key from Secrets Manager
`homeai/alert-view-hmac`, cached 5 min.

### 4.5 Jobs (APScheduler in the API process; guard with a Postgres advisory lock so only one runs)
| Job | Every | Does |
|---|---|---|
| NotificationRetry | 60 s | `failed` email notifications with `attempt_count < 3` and `next_attempt_at ≤ now` → re-check subscription, republish; at most 3 attempts in total: next try +1 min after attempt 1, +2 min after attempt 2, then leave `failed`. Also email rows still `queued` 5 min after `created_at` (a crash between insert and send). Contacts are re-read from C4 per house: removed → stop (`contact_removed`), changed email → current address (`SnsGateway.ensure_subscription` unsubscribes the old address's confirmed subscription with the same `contact_id` filter policy when it creates the new one; also on first sends), C4 down → try next run without using an attempt; an unexpected error counts as an attempt. Alert `false_positive`/`resolved` → stop (`alert_closed`); `acknowledged` is still emailed. Batch of 100, oldest first |
| ContactSubscriptionSync | 5 min | for houses with contacts **and** houses that still have a `homeai-house-*` topic: ensure topic + subscription per contact (filter policy), unsubscribe addresses that are no longer contacts; logs pending confirmations. A pending subscription of a former contact is left alone (AWS cannot unsubscribe `PendingConfirmation`; it lapses after 3 days). SNS failure skips that house only |

Implementation (`app/jobs/`): `JobRunner` (built in `create_app`, `app.state.jobs`) opens its own
sessions (`c2_app`, `c2_reader`) per run; the lock is `pg_try_advisory_xact_lock` on a separate
connection held for the whole run (the job commits row by row, which would release a lock taken
on its own session), keys `RETRY_LOCK` / `SYNC_LOCK`. A run whose lock is held elsewhere is
skipped. `C2_JOBS_ENABLED=0` turns the scheduler off (tests do).

---
## 5. Code structure
```
app/api/{alerts.py, lifecycle.py, evaluate.py, rules.py, alert_types.py, alert_view.py, health.py}
app/schemas/{alert.py, rule.py, evaluate.py, alert_view.py}
app/services/{rule_engine.py, lifecycle.py, notification_service.py, signed_link.py, quiet_hours.py, rule_service.py, stats_service.py, access_policy.py}
app/repositories/{alert_repo.py, rule_repo.py, alert_type_repo.py, history_repo.py, notification_repo.py}
app/gateways/{detection_gateway.py (Mongo reader), c4_settings_gateway.py, c1_house_gateway.py, c1_clip_client.py, sns_gateway.py, log_notifier.py, secrets_gateway.py}
app/jobs/{notification_retry.py, subscription_sync.py}
scripts/demo/c2_fake_detection.py      # DEMO_MODE: insert a detection doc + call evaluate with a c3 service token
scripts/demo/c2_expired_link.py        # prints an already-expired alert-view link for the demo
app/seed.py                            # tenant default rules for the seed tenants (python -m app.seed)
```
Demo scripts use the shared seed IDs in `scripts/seed_ids.py` (`--house maple`, `--room Kitchen`).
`c2_fake_detection.py` gets a `c3-worker` token from C4 (needs the seeded service clients) or takes
`--token`; evaluate also needs C1's houses (until C1 lands it answers 503 `c1`).

---
## 6. UI (feature folder `c2-alerts`) — D2 wireframes
| Page | Key elements | API |
|---|---|---|
| **Alerts** `/alerts` | FilterBar (status, severity, type, house, date); DataTable (SeverityBadge, type, house/room, status chip, triggered "2 m ago"); polls every 15 s; banner "1 new critical alert" when a new critical arrives | `GET /alerts` |
| **Alert Detail** `/alerts/:id` | Header (SeverityBadge, type, room, house, time, StatusChip); Evidence ClipPlayer (C1 playback URL); ConfidenceBars with matched label + threshold; Timeline; Contacts notified table (sent / retry n/3 / failed / pending confirmation; demo link if DEMO_MODE); ActionBar: Acknowledge / Resolve / Mark false positive enabled only per state machine; note textarea; false-positive confirm dialog requiring reason | `GET /alerts/{id}`, actions, C1 playback |
| **Alert Rules** `/ops/alert-rules` | FilterBar (tenant, house, type, enabled); table (type, labels, min conf, room, severity, scope, enabled, false positives 30 d); FormPanel create/edit with inline 422 errors, 409 duplicate toast, 412 reload; Disable (confirm); "Create tenant defaults"; "Sync email subscriptions" button showing pending confirmations | rules endpoints |
| **Alert View** `/alert-view/:token` (public, no shell, mobile-first) | severity, title, room/house/time, status, labels, play clip, "call 911" notice, expiry; expired (401) and not-found (404) states | `GET /alert-view/{token}` |

---
## 7. Tests
Unit (no DB): rule precedence ordering; threshold with sensitivity incl. clamp; quiet hours (wrap midnight,
timezone, DST day); reason precedence; transition table (all 4 states × 3 actions); signed link
(valid, tampered, expired, wrong kid); notification channel by severity; email rendering.
API (Postgres + Mongo + LocalStack SNS): evaluate → 201 + history + notifications; replay → duplicate;
concurrent evaluate same detection (two threads) → one alert; below threshold / service disabled / quiet
hours low vs high; room mismatch; owner cannot see other house (403); acknowledge→resolve; resolve on open
409; false positive without reason 422; concurrent acknowledge (one 409); rules CRUD, duplicate 409,
If-Match 412; alert-view 200/401/404; stats grouping. Coverage ≥ 80% on `services/`.

---
## 8. Task list
| ID | Task | Depends |
|---|---|---|
| C2-01 | Skeleton, settings, health, Alembic baseline (P0-6) | P0-3 |
| C2-02 | Migrations 0001/0002, ORM, repositories | C2-01 |
| C2-03 | Gateways: c4 settings/contacts reader, c1 house reader, detection reader (Mongo), with fakes for tests | C2-02 |
| C2-04 | Alert types + rules API (validation, duplicate, If-Match, soft delete, defaults) + tests | C2-02 |
| C2-05 | RuleEngine + quiet hours + sensitivity + precedence (unit tests first) | C2-03, C2-04 |
| C2-06 | Lifecycle service, alerts list/detail/stats, actions endpoints + tests | C2-05 |
| C2-07 | `POST /alerts/evaluate` with service scope + idempotency race test | C2-05, C2-06 |
| C2-08 | Signed link service + `GET /alert-view/{token}` + rate limit | C2-06 |
| C2-09 | Notifier abstraction: LogNotifier, SnsGateway (LocalStack), NotificationService + tests | C2-07, C2-08 |
| C2-10 | Jobs: NotificationRetry, ContactSubscriptionSync (+ advisory lock) + sync endpoint | C2-09 |
| C2-11 | C1 playback client (service token) in detail + alert view | C1-07 |
| C2-12 | Demo scripts (`c2_fake_detection.py`, `c2_expired_link.py`), seed rules | C2-07 |
| C2-13 | UI: api/c2.ts, Alerts list (polling), Alert Detail | C2-06, P0-8 |
| C2-14 | UI: Alert Rules page | C2-04 |
| C2-15 | UI: public Alert View | C2-08 |
| C2-16 | Integration with C3 (real detections) and C4 settings (quiet hours, sensitivity) — tests I-2, I-3 | C3-09, C4-06 |
| C2-17 | AWS: real SNS, confirm demo subscriptions, Playwright `e2e/c2-alert-lifecycle.spec.ts`, video | infra §8 |

## 9. Acceptance checklist
- [ ] Every row of the rule-match, transition, rule-validation and signed-link decision tables (D2 §4) has a test.
- [ ] Same detection never creates two alerts (replay + concurrency tests).
- [ ] Critical/high alerts email contacts in priority order through real SNS; medium/low only in-app.
- [ ] Quiet hours hold only medium/low; house sensitivity shifts thresholds ±0.10.
- [ ] Owner sees only own houses; invalid transitions return 409 and the UI disables those buttons.
- [ ] Signed link works without login, expires after 24 h, leaks no PII.

---
## 10. Deliverable #3 demo (C2)
### 10.1 Live demo (≈ 8 min)
1. `ops@homeai.test` → **Alert Rules**: show tenant defaults; create a house rule for `fall` in Bathroom with
   min 0.70; try duplicate → 409; invalid label → 422 inline; disable/enable.
2. Trigger a detection: upload `glass_break.wav` in C1 Feed Detail (full pipeline) — fallback:
   `python scripts/demo/c2_fake_detection.py --label glass_break --conf 0.78 --house maple`.
3. Alert appears (≤ 15 s) in **Alerts** for `owner.maple@acme.test`; email arrives on a phone (SNS) in
   contact priority order; open the link on the phone → **Alert View** (no login).
4. **Alert Detail**: play clip, labels with threshold, timeline, contacts (sent / pending). Acknowledge with a
   note → Resolve. Show Resolve was disabled while open; show 409 via Swagger for resolve-on-open.
5. **Quiet hours + severity** (C4 settings): set quiet hours to cover now → upload `cough.wav` (low) →
   `no_alert quiet_hours` in logs/response; upload `glass_break.wav` (high) → alert raised (bypass).
6. Idempotency: re-send the same evaluate payload → `duplicate:true` (`c2_fake_detection.py --resend <detection_id>`, printed by the first run). Expired link → 401 page (`python scripts/demo/c2_expired_link.py` prints one for the newest alert).
7. Unit demo: `make test-c2` with coverage; Swagger `/api/v1/docs/c2`.
### 10.2 Scenario video (≈ 5 min) — "Night-time break-in at Maple St"
Glass-break clip arrives at 23:10 during quiet hours → high-severity intrusion alert bypasses quiet hours →
contacts emailed in order → neighbor opens the signed link → owner acknowledges, checks the clip, resolves
with a note. Then a cough during quiet hours is held (no alert). End with Alert Rules tuning after a false positive.
### 10.3 Prep
Confirm SNS subscriptions for 2–3 team emails (click confirmation links), set quiet hours for the demo time,
seed rules, pre-open phone browser, have `c2_fake_detection.py` ready as fallback.

---
## 11. Stand-ins (temporary until teammates' work lands)
Each one is tagged in code with `# STANDIN(<trigger>)`; list them with `grep -rn STANDIN services .github`.
When the trigger lands, do the action, delete the tag and tick the row. C2-16 (integration) is the
deadline for all of them.

| Done | Tag | Stand-in | Where | Trigger | Action |
|---|---|---|---|---|---|
| [ ] | `STANDIN(C1-02)` | c1/c4 tables built from copied DDL in tests | `tests/db/foreign_tables.py` | C1 migration 0001 (Ekant) | Build them by running the real C1 + C4 migrations in the test DB; delete the DDL. Also update `test_real_reader_wiring_reports_c1_not_deployed` in `tests/db/test_rules_api.py` (503 `c1` → 422 unknown house) and `test_default_wiring_uses_the_configured_databases` in `tests/db/test_jobs.py` (503 `c4` → a real sync result) |
| [ ] | `STANDIN(contracts)` | Local `Detection` model for `ai_detections` | `app/gateways/types.py` | `homeai_common/contracts.py` (all owners) | Import `DetectionDoc`; delete the local classes |
| [x] | `STANDIN(P0-5)` | Tests connect as the Postgres superuser | `tests/db/conftest.py` | `infra/db/init.sql` roles + grants (Renuka) | Add tests: `c2_reader` reads only the §4.5 tables and cannot write. Done in `tests/db/test_reader_grants.py` (tables created as `c1_app`/`c4_app`, checked with `SET ROLE c2_reader`); test tables get the same grants as the owning migrations (C4 0002, C1 0001), so "reads *only* those tables" is checked too |
| [x] | `STANDIN(P0-5)` | CI creates schemas when `init.sql` is missing | `.github/workflows/ci.yml` | `infra/db/init.sql` (Renuka) | CI switches automatically; delete the fallback branch. Done: CI always runs `init.sql` |
| [ ] | `STANDIN(C1-07)` *(C2-11)* | Playback URL `null` ("clip unavailable") | `app/services/alert_view.py` (`clip_url`); `web/src/features/c2-alerts/AlertDetailPage.tsx` ("Clip playback is not available yet") | C1 `GET /clips/{id}/playback-url` (Ekant) | Call it with service scope `clips:playback` |
| [ ] | `STANDIN(C1 houses API)` *(C2-14)* | Alert Rules form takes house / room as typed ids; the table shows short ids | `web/src/features/c2-alerts/RuleForm.tsx`, `RulesPage.tsx` | C1 `GET /houses`, `GET /houses/{id}/rooms` (Ekant) | Replace the id inputs with house and room pickers; show names in the table |
| [ ] | — *(C2-16)* | Detections faked with `c2_fake_detection.py` in integration | demo scripts | C3 worker handoff (Renuka, C3-09) **landed 5 Nov**; still needs C1 (houses, clips) and `HANDOFF_MODE=call` for `c3-worker` in compose | Run I-2/I-3 with real detections; keep the script as the demo fallback |
Permanent (not stand-ins): `tests/fakes.py` readers (kept honest by shared tests with the real
gateways), `homeai_common.testing` keys, `NOTIFIER=log`, `alembic/env.py` creating schema `c2` if missing.
