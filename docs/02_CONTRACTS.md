# 02 — Contracts (binding for all components)

Everything in this file is shared. Changing it needs agreement from the owners it affects and an entry in
`docs/CHANGELOG.md`. The shared library `libs/homeai_common` implements sections 1–4 so no service
re-implements them.

---
## 1. HTTP conventions
| Aspect | Rule |
|---|---|
| Base | `https://<host>/api/v1/...`; JSON UTF-8; multipart only for file upload |
| Success body | `{"data": <object or array>, "meta": {...}}` — `meta` only on lists or when documented |
| List meta | `{"page": 1, "page_size": 25, "total": 134}`; `page` ≥ 1, `page_size` 1–100 (default 25) |
| Sorting | newest first by the entity's main timestamp unless `sort=<field>` / `sort=-<field>` is documented |
| Error body | `{"error": {"code": "snake_case", "message": "human text", "details": {...} or [...]}}` |
| Validation errors | HTTP 422, `code: "validation_error"`, `details: [{"field": "min_confidence", "issue": "must be between 0 and 1"}]` (map FastAPI's `RequestValidationError` to this shape) |
| Request id | Every response has `X-Request-Id` (echo incoming header or generate UUID); log it |
| Time | ISO-8601 UTC with `Z` (`2026-10-31T14:32:05Z`); house-local times only where named (`quiet_start`) |
| IDs | UUID v4 strings, lowercase, everywhere (including MongoDB `_id`) |
| Empty results | `200` with `data: []`, never `404` |
| Docs | Each service: `openapi_url=/api/v1/docs/<cx>/openapi.json`, `docs_url=/api/v1/docs/<cx>` |
| Health | `GET /api/v1/health/<cx>` → `{"status":"ok","db":"ok","mongo":"ok","version":"<git sha>"}` (no auth) |

### 1.1 Shared error codes
| HTTP | code | Used by |
|---|---|---|
| 400 | `bad_request` | all |
| 401 | `unauthorized`, `token_expired`, `token_revoked`, `invalid_credentials` | all / C4 login |
| 403 | `forbidden` | all |
| 404 | `not_found`, `unknown_entity` | all / C3 records |
| 409 | `invalid_state`, `duplicate_rule` (C2); `feed_not_enabled`, `room_required`, `house_not_empty`, `room_in_use` (C1); `already_analyzed`, `check_running`, `not_failed`, `model_active` (C3); `contact_limit`, `email_exists` (C4) | owners |
| 412 | `version_mismatch` | C2 rules |
| 413 | `payload_too_large` | C1 ingest, C3 model upload |
| 422 | `validation_error`, `media_kind_mismatch` (C1), `unreadable_clip` (C3) | all |
| 423 | `account_locked` | C4 |
| 429 | `rate_limited` | C2 alert-view, C3 records, C4 login |
| 503 | `dependency_unavailable`, `storage_unavailable` | all |

---
## 2. Identity, tokens and roles

### 2.1 Roles
| Role | Scope of data | Notes |
|---|---|---|
| `house_owner` | Houses in JWT `house_ids` | Settings, contacts, own alerts, own feeds/clips read-only |
| `iot_staff` | All houses of JWT `tenant_id` | Houses, rooms, feeds, ingest, clips |
| `cloud_staff` | **All tenants** (platform operators) | Rules, tenants, users, records, models, integrity. When an action needs a tenant and no `house_id` gives it, the request must carry `tenant_id` (query or body) |
| service (no role) | JWT `scope` list | Component-to-component calls |
| external recipient | One alert via signed link | No JWT; HMAC token handled by C2 only |

### 2.2 User JWT (issued by C4 `POST /auth/login`)
- Algorithm **RS256**, header `kid` = key id. TTL **60 minutes**. No refresh token (re-login).
- Claims:
```json
{ "iss": "homeai-c4", "aud": "homeai", "typ": "user",
  "sub": "<user_id>", "role": "house_owner|iot_staff|cloud_staff",
  "tenant_id": "<uuid>", "house_ids": ["<uuid>", "..."], "email": "ruth@example.com",
  "jti": "<uuid>", "iat": 1792196400, "exp": 1792200000 }
```

### 2.3 Service JWT (issued by C4 `POST /auth/service-token`)
- Same keys/algorithm. TTL **15 minutes**; clients cache and refresh at 80% of TTL.
```json
{ "iss": "homeai-c4", "aud": "homeai", "typ": "service", "sub": "c3-worker",
  "scope": ["alerts:evaluate"], "jti": "<uuid>", "iat": 0, "exp": 0 }
```
| client_id | Scopes | Used for |
|---|---|---|
| `c1-iot` | `stats:read` (none needed today) | — |
| `c2-alerts` | `clips:playback` | C2 → C1 playback URL |
| `c3-worker` / `c3-data` | `alerts:evaluate` | C3 → C2 evaluate |
| `c4-dashboard` | `feeds:read`, `alerts:read`, `records:read` | C4 → C1/C2/C3 stats |
| `device-uploader` | `ingest:write` | Upload client / device simulator → C1 ingest |

### 2.4 Verification (all services, via `homeai_common.auth`)
1. Fetch `GET https://<host>/.well-known/jwks.json` (internal: `http://c4-dashboard:8004/.well-known/jwks.json`); cache 10 min; refetch on unknown `kid`.
2. Verify signature, `iss`, `aud`, `exp` (60 s leeway).
3. For `typ=user`: reject if `jti` is revoked (C4 exposes `GET /auth/revoked?since=<ts>`; cache list 60 s) — **only C4 enforces denylist strictly; other services check the cached list**.
4. Build `Principal(kind, user_id|client_id, role, tenant_id, house_ids, scopes)` and pass it to handlers.
5. Helpers: `require_roles(*roles)`, `require_scope(scope)`, `assert_house(principal, house_id, tenant_id_of_house)`, `tenant_filter(principal)`.

---
## 3. Canonical enumerations (use these exact strings)
| Name | Values |
|---|---|
| media_kind | `audio`, `video` |
| feed status | `provisioned`, `active`, `inactive`, `error` |
| connectivity_status | `online`, `offline`, `unknown` |
| capture sensitivity (C1) | `low`, `medium`, `high` |
| room_type | `bedroom`, `kitchen`, `living`, `bathroom`, `entry`, `other` |
| clip status (`media_events.status`) | `queued`, `processing`, `analyzed`, `failed` |
| handoff_status | `none`, `done`, `pending` |
| home labels (C3 label map) | `smoke_alarm`, `distress_sound`, `glass_break`, `fall_indicator`, `cough`, `speech`, `dog` |
| alert type codes (C2) | `smoke`, `distress`, `intrusion`, `fall`, `wellness_cough`, `presence`, `pet` |
| service codes (C4 settings) | `fire_safety`, `distress`, `intrusion`, `fall`, `wellness`, `presence`, `pet` |
| alert category | `emergency`, `safety`, `security`, `wellness`, `system` |
| severity | `critical`, `high`, `medium`, `low` |
| alert status | `open`, `acknowledged`, `resolved`, `false_positive` |
| no_alert reason | `service_disabled`, `no_rule_match`, `below_threshold`, `room_mismatch`, `quiet_hours` |
| notification channel / status | `in_app`, `email` / `queued`, `sent`, `failed` |
| house sensitivity (C4) | `low` (+0.10), `medium` (0), `high` (−0.10) applied to rule `min_confidence`, clamp 0.05–0.95 |
| contact_type | `family`, `caregiver`, `neighbor`, `emergency_service` |
| model status (C3) | `registered`, `evaluated`, `active`, `retired` |
| integrity report status | `running`, `done`, `failed` |

Alert type ↔ label ↔ service mapping (seeded by C2):
| alert type | trigger label | category | default severity | default min_confidence | service code |
|---|---|---|---|---|---|
| smoke | smoke_alarm | emergency | critical | 0.50 | fire_safety |
| distress | distress_sound | emergency | critical | 0.60 | distress |
| intrusion | glass_break | security | high | 0.55 | intrusion |
| fall | fall_indicator | safety | high | 0.65 | fall |
| wellness_cough | cough | wellness | low | 0.55 | wellness |
| presence | speech | wellness | low | 0.50 | presence |
| pet | dog | wellness | low | 0.55 | pet |

Quiet hours suppress only `medium` and `low` alerts; `critical` and `high` always go through.

---
## 4. Cross-component contracts

### 4.1 `media_events` document (MongoDB `homeai.media_events`; owner C1)
```json
{ "_id": "9b1e2f40-6c3d-4e1a-9f0b-2c8d1a7e5b07",
  "tenant_id": "uuid", "house_id": "uuid", "room_id": "uuid", "feed_id": "uuid",
  "media_kind": "audio",
  "s3": {"bucket": "homeai-clips-team", "key": "tenants/../9b1e2f40.wav", "size": 320044, "content_type": "audio/wav"},
  "captured_at": "2026-10-24T18:40:41Z", "uploaded_at": "2026-10-24T18:40:43Z",
  "client_clip_id": "kitchen-1840" ,
  "status": "queued",
  "attempts": 0, "claimed_at": null, "worker_id": null, "error": null, "detection_id": null, "handoff_status": "none" }
```
C1 inserts all fields with `status=queued`, `attempts=0`, `handoff_status="none"`. **Only C3** updates
`status`, `attempts`, `claimed_at`, `worker_id`, `error`, `detection_id`, `handoff_status`. Indexes (created by C1's
migration script): `{status:1, uploaded_at:1}`, `{house_id:1, captured_at:-1}`,
`{feed_id:1, client_clip_id:1}` unique partial (`client_clip_id` exists).

### 4.2 `ai_detections` document (MongoDB `homeai.ai_detections`; owner C3; C2 reads)
```json
{ "_id": "3f2a7c10-...", "media_id": "9b1e2f40-...", "tenant_id": "uuid", "house_id": "uuid", "room_id": "uuid",
  "model": {"model_id": "uuid", "name": "yamnet", "version": "1.0.0"},
  "labels": [ {"label": "glass_break", "confidence": 0.78, "source_class": "Glass", "start_s": 2.9, "end_s": 4.8} ],
  "top_label": "glass_break", "top_confidence": 0.78, "detected_at": "2026-10-24T18:40:50Z" }
```
If no label passes its threshold: `labels: []`, `top_label: "none"`, `top_confidence: 0.0`.

### 4.3 C3 → C2 `POST /api/v1/alerts/evaluate` (service JWT scope `alerts:evaluate`)
Request:
```json
{ "detection_id": "uuid", "media_id": "uuid", "house_id": "uuid", "room_id": "uuid or null",
  "top_label": "glass_break", "top_confidence": 0.78,
  "labels": [{"label": "glass_break", "confidence": 0.78}], "detected_at": "2026-10-24T18:40:50Z" }
```
Responses: `201 {"data":{"decision":"alert","alert_id":"uuid","severity":"high","duplicate":false}}`;
`200 {"data":{"decision":"alert","alert_id":"uuid","duplicate":true}}`;
`200 {"data":{"decision":"no_alert","reason":"below_threshold"}}`; `503` → caller retries (2/4/8 s).

### 4.4 C2 → C1 `GET /api/v1/clips/{media_id}/playback-url` (user JWT in scope, or service scope `clips:playback`)
`200 {"data":{"url":"https://...presigned...","expires_at":"2026-10-31T14:47:05Z"}}` (15 minutes).

### 4.5 Read-only SQL used by C2 (role `c2_reader`)
```sql
SELECT house_id, tenant_id, enabled_services, quiet_start, quiet_end, sensitivity FROM c4.house_service_settings WHERE house_id = :h;
SELECT contact_id, name, email, contact_type, priority FROM c4.emergency_contacts WHERE house_id = :h ORDER BY priority;
SELECT house_id, tenant_id, name, timezone FROM c1.houses WHERE house_id = :h AND deleted_at IS NULL;
SELECT room_id, name FROM c1.rooms WHERE room_id = :r;
```
If a house has no settings row, C2 treats it as: all services enabled, no quiet hours, sensitivity `medium`.

### 4.6 Statistics endpoints used by C4 (service scopes `feeds:read`, `alerts:read`, `records:read`)
| Endpoint | Response `data` |
|---|---|
| C1 `GET /feeds/stats?tenant_id=&house_id=` | `{"houses": 3, "total": 9, "by_status": {"active": 6, "inactive": 1, "provisioned": 1, "error": 1}, "online": 6}` |
| C2 `GET /alerts/stats?group_by=severity&from=&to=&house_id=` | `[{"key":"critical","count":4}, ...]` (also `group_by=alert_type|house|day`) |
| C3 `GET /detections/stats?group_by=top_label&from=&to=&house_id=` | `[{"key":"speech","count":3100}, ...]` plus `meta.total_clips` |

### 4.7 C4 auth endpoints used by all
- `GET /.well-known/jwks.json` → `{"keys":[{"kty":"RSA","kid":"2026-11","use":"sig","alg":"RS256","n":"...","e":"AQAB"}]}`
- `POST /api/v1/auth/service-token` body `{"client_id","client_secret","scope":["alerts:evaluate"]}` → `{"data":{"token","expires_in":900}}`
- `GET /api/v1/auth/revoked?since=<iso>` (service scope any) → `{"data":["jti", ...]}`

---
## 5. Data stores and access
### 5.1 PostgreSQL (one RDS instance, database `homeai`)
| Schema | Owner role (read/write) | Read-only roles granted |
|---|---|---|
| `c1` | `c1_app` | `c2_reader` (houses, rooms only), `c3_reader`, `c4_reader` |
| `c2` | `c2_app` | `c3_reader` |
| `c3` | `c3_app` | — |
| `c4` | `c4_app` | `c2_reader` (house_service_settings, emergency_contacts only), `c3_reader` (all except password_hash, secret_hash via a view `c4.users_public`) |
Each service connects as `cX_app`; its read-only connection (if any) uses `cX_reader`. Migrations: Alembic,
one `alembic/` per service, `version_table_schema` = own schema. `infra/db/init.sql` creates schemas, roles and grants.

### 5.2 MongoDB (container `mongo:7`, database `homeai`)
| Collection | Owner (readWrite) | Readers |
|---|---|---|
| `media_events` | `c1_app` (insert), `c3_app` (update processing fields) | c3, c4 (counts) |
| `ai_detections` | `c3_app` | `c2_reader`, c4 |
| `activity_patterns` | `c3_app` | c4 |
| `dashboard_stats_daily` | `c4_app` | — |
Users created by `infra/mongo/init.js`.

### 5.3 S3 (one bucket `homeai-<team>-<acct>`; SSE-S3; public access blocked)
| Prefix | Owner |
|---|---|
| `tenants/{tenant}/houses/{house}/feeds/{feed}/yyyy/mm/dd/{media_id}.{ext}` | C1 (write), C3 (read) |
| `models/{name}/{version}/...` | C3 |
| `backups/{yyyy-mm-dd}/postgres.dump`, `backups/{yyyy-mm-dd}/mongo.archive.gz` | C3 |

---
## 6. Logging, metrics, jobs
- JSON logs to stdout: `ts, level, service, request_id, tenant_id, user_id, msg, extra`. Never log passwords, tokens or full emails.
- Every scheduled job logs start/end and counts; jobs must be idempotent and safe to run on one instance.
- Optional CloudWatch Agent on EC2 ships container logs (`/homeai/<service>` log groups).
