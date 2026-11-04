# C1 — Home-Based IoT Device Manager — Implementation Plan
**Owner:** Ekant Kapgate · **Service:** `services/c1_iot` (port 8001) · **UI:** `web/src/features/c1-iot`
**Reads first:** `AGENTS.md`, `docs/01`–`04`. Design reference: D2 Part I (C1).

## 0. Goal in one line
Model houses/rooms, manage camera feeds with versioned config, ingest clips exactly once into S3 +
`media_events` (status `queued`), derive connectivity, and give staff/owners a Clip Library with signed playback.

---
## 1. Scope
**In:** houses, rooms, camera feeds, feed config versions + restore, enable/disable/archive, clip ingest
(validation, idempotency, S3 write, record, compensation), connectivity monitor, Clip Library, playback URLs,
feed statistics for C4 **[D3 addition]**, device simulator script, C1 UI pages.
**Out:** classification (C3), alerts (C2), users/login/house assignment to owners (C4 — `users.house_ids`).

### 1.1 Dependencies
| Needs | From | When | Stub until ready |
|---|---|---|---|
| JWT verification (JWKS) | C4 / `homeai_common.auth` | P0-4/P0-7 (week 1) | `homeai_common.testing` test keys |
| Nothing else | — | — | — |
| **Provides** | **To** | | |
| `media_events` queued docs (contract 4.1) | C3 worker | week 2 | — |
| `GET /clips/{id}/playback-url` | C2 Alert Detail / alert view, C3 records | week 3 | — |
| `c1.houses`, `c1.rooms` read-only | C2 (timezone, names), C3 | week 2 | — |
| `GET /feeds/stats` | C4 dashboards | week 3 | — |
C1 is the most independent component: it can be fully built and demoed with only C4 login.

---
## 2. Data model
### 2.1 PostgreSQL schema `c1` (Alembic `0001_initial`)
```sql
CREATE TABLE c1.houses (
  house_id      UUID PRIMARY KEY,
  tenant_id     UUID NOT NULL,
  name          VARCHAR(80)  NOT NULL,
  address       VARCHAR(200),
  timezone      VARCHAR(40)  NOT NULL,              -- IANA, validated with zoneinfo
  owner_user_id UUID,                               -- informational; access comes from C4 users.house_ids
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at    TIMESTAMPTZ
);
CREATE UNIQUE INDEX ux_houses_tenant_name ON c1.houses(tenant_id, name) WHERE deleted_at IS NULL;

CREATE TABLE c1.rooms (
  room_id    UUID PRIMARY KEY,
  house_id   UUID NOT NULL REFERENCES c1.houses(house_id),
  name       VARCHAR(60) NOT NULL,
  room_type  VARCHAR(12) NOT NULL CHECK (room_type IN ('bedroom','kitchen','living','bathroom','entry','other')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (house_id, name)
);

CREATE TABLE c1.camera_feeds (
  feed_id              UUID PRIMARY KEY,
  tenant_id            UUID NOT NULL,
  house_id             UUID NOT NULL REFERENCES c1.houses(house_id),
  room_id              UUID REFERENCES c1.rooms(room_id),
  name                 VARCHAR(80) NOT NULL,
  media_kind           VARCHAR(5)  NOT NULL CHECK (media_kind IN ('audio','video')),
  status               VARCHAR(12) NOT NULL DEFAULT 'provisioned' CHECK (status IN ('provisioned','active','inactive','error')),
  is_enabled           BOOLEAN NOT NULL DEFAULT false,
  connectivity_status  VARCHAR(8)  NOT NULL DEFAULT 'unknown' CHECK (connectivity_status IN ('online','offline','unknown')),
  config               JSONB NOT NULL,              -- copy of current version {capture_interval_s, sensitivity, network_label}
  config_version       INT NOT NULL DEFAULT 1,
  last_clip_at         TIMESTAMPTZ,
  consecutive_failures SMALLINT NOT NULL DEFAULT 0,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  archived_at          TIMESTAMPTZ
);
CREATE UNIQUE INDEX ux_feeds_house_name ON c1.camera_feeds(house_id, name) WHERE archived_at IS NULL;
CREATE INDEX ix_feeds_scope ON c1.camera_feeds(tenant_id, house_id, status);

CREATE TABLE c1.feed_config_versions (
  feed_id            UUID NOT NULL REFERENCES c1.camera_feeds(feed_id),
  version            INT  NOT NULL,
  capture_interval_s INT  NOT NULL CHECK (capture_interval_s BETWEEN 5 AND 3600),
  sensitivity        VARCHAR(6) NOT NULL CHECK (sensitivity IN ('low','medium','high')),
  network_label      VARCHAR(60),
  created_by         UUID NOT NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (feed_id, version)
);
```
Grants (contract 02 §5.1): `infra/db/init.sql` gives `c3_reader`/`c4_reader` every c1 table, but `c2_reader` may read only houses and rooms, so `0001_initial` must end with `GRANT SELECT ON c1.houses, c1.rooms TO c2_reader` (skip it if the role does not exist; see C4 migration `0002_reader_grants.py`) and `downgrade()` revokes it. Without it C2 answers 503 `c1`.
### 2.2 MongoDB `media_events` (owner C1) — exact document in `02_CONTRACTS.md` §4.1
Create indexes in a startup hook `ensure_indexes()`: `{status:1, uploaded_at:1}`,
`{house_id:1, captured_at:-1}`, `{feed_id:1, client_clip_id:1}` unique with
`partialFilterExpression: {client_clip_id: {$exists: true}}`.

### 2.3 S3
Key: `tenants/{tenant_id}/houses/{house_id}/feeds/{feed_id}/{yyyy}/{mm}/{dd}/{media_id}.{ext}`
(`ext` from content type: `audio/wav`→`wav`, `audio/mpeg`→`mp3`, `video/mp4`→`mp4`). `ServerSideEncryption=AES256`.

---
## 3. API (all under `/api/v1`; envelope/errors per contracts)
Access legend: **S** = iot_staff (own tenant) or cloud_staff (any tenant), **O** = house_owner (own houses, read-only).

### 3.1 Houses and rooms
| Method & path | Access | Request | Response / rules |
|---|---|---|---|
| `GET /houses` | S, O | `page`, `page_size`, `tenant_id` (cloud_staff only), `q` (name contains) | owners see only `house_ids`; excludes deleted |
| `POST /houses` | S | `{name, address?, timezone, owner_user_id?, tenant_id? (cloud_staff required), house_id? (DEMO_MODE only)}` | 201 House; 422 `validation_error` for a bad timezone or a duplicate name in the tenant (field `name`) |
| `GET /houses/{id}` | S, O | — | House + `room_count`, `feed_count` |
| `PATCH /houses/{id}` | S | any of `name, address, timezone, owner_user_id` | 200 |
| `DELETE /houses/{id}` | S | — | 409 `house_not_empty` if any feed `is_enabled`; else set `deleted_at`, 204 |
| `GET /houses/{id}/rooms` | S, O | — | list (no paging needed, ≤ 50) |
| `POST /houses/{id}/rooms` | S | `{name, room_type}` | 201 Room |
| `PATCH /rooms/{id}` | S | `{name?, room_type?}` | 200 |
| `DELETE /rooms/{id}` | S | — | 409 `room_in_use` if any non-archived feed has this room; else 204 |

### 3.2 Feeds
| Method & path | Access | Request | Response / rules |
|---|---|---|---|
| `GET /feeds` | S, O | `house_id, room_id, media_kind, status, connectivity_status, is_enabled, include_archived=false, page, page_size` | list of Feed (shape below) |
| `POST /feeds` | S | `{name, media_kind, house_id, room_id?, config:{capture_interval_s, sensitivity, network_label?}}` | 201 Feed (`provisioned`, disabled, `config_version=1`); room must belong to house (422) |
| `GET /feeds/{id}` | S, O | — | Feed + `recent_clips` (last 5) |
| `PATCH /feeds/{id}` | S | `{name?, room_id?}` | 200; setting `room_id=null` on an enabled feed → 409 `room_required` |
| `PATCH /feeds/{id}/status` | S | `{is_enabled: bool}` | enable needs room (409 `room_required`); enabling a feed in `error` resets `status=provisioned`, `consecutive_failures=0` |
| `DELETE /feeds/{id}` | S | — | archive: `is_enabled=false`, `archived_at=now()`; 204 |
| `PUT /feeds/{id}/config` | S | `{capture_interval_s, sensitivity, network_label?}` | 200 `{config_version, config}`; new version n+1 |
| `GET /feeds/{id}/config-versions` | S | — | list newest first |
| `POST /feeds/{id}/config-versions/{v}/restore` | S | — | copies v into n+1; 404 unknown v |
| `GET /feeds/stats` **[D3]** | S, service `feeds:read` | `tenant_id?`, `house_id?` | `{houses, total, by_status:{...}, online}` (contract 4.6) |
Feed JSON: `{feed_id, tenant_id, house_id, house_name, room_id, room_name, name, media_kind, status,
is_enabled, connectivity_status, config, config_version, last_clip_at, created_at, archived_at}`.

### 3.3 Ingest and clips
| Method & path | Access | Request | Response / rules |
|---|---|---|---|
| `POST /ingest/clip` | iot_staff/cloud_staff JWT or service `ingest:write` | multipart: `feed_id, media_kind, captured_at, client_clip_id?, file` | 201 `{media_id, status:"queued", s3_key, duplicate:false}`; 200 `duplicate:true`; errors per decision table §4.1 |
| `GET /clips` | S, O | `house_id, feed_id, room_id, status, from, to, page, page_size` | `{media_id, feed_id, feed_name, room_name, media_kind, captured_at, uploaded_at, size, status, detection_id}` |
| `GET /clips/{media_id}` | S, O | — | full record + `top_label` (read from `ai_detections` if present, optional) |
| `GET /clips/{media_id}/playback-url` | S, O, service `clips:playback` | — | `{url, expires_at}` (15 min presign) |
Limits: file ≤ 50 MB (`413`), content types `audio/wav`, `audio/x-wav`, `audio/mpeg`, `video/mp4`;
`captured_at` ≤ now + 5 min (422). Caddy limit 60 MB.

---
## 4. Business logic
### 4.1 Ingest decision table (implement in `IngestService.ingest`, in this order)
| # | Check | Fail result |
|---|---|---|
| 1 | caller authenticated with allowed role/scope | 401/403 |
| 2 | feed exists, not archived, in caller tenant (service tokens: any tenant) | 404 `not_found` |
| 3 | `is_enabled` and `room_id` not null | 409 `feed_not_enabled` |
| 4 | `media_kind` equals feed kind | 422 `media_kind_mismatch` |
| 5 | content type allowed, size ≤ 50 MB, `captured_at` sane | 413 / 422 |
| 6 | `client_clip_id` already stored for this feed | 200 existing record, `duplicate:true` |
| 7 | generate `media_id=uuid4()`, build key, `put_object` | 503 `storage_unavailable`, `consecutive_failures += 1` |
| 8 | insert `media_events` (`status=queued`) | delete S3 object, 503, failures += 1 |
| 9 | `touch_last_clip`: `last_clip_at=max(..)`, `connectivity_status=online`, `status: provisioned|inactive → active`, `consecutive_failures=0` | — |
If `consecutive_failures` reaches 3 → `status=error`.

### 4.2 ConnectivityMonitor (APScheduler, every 60 s, only enabled non-archived feeds)
| Condition | connectivity_status | status |
|---|---|---|
| `last_clip_at` is null | `unknown` | unchanged (`provisioned`) |
| `now - last_clip_at ≤ capture_interval_s` | `online` | `active` (unless `error`) |
| otherwise | `offline` | `inactive` (unless `error`) |
Update only rows that change (one `UPDATE ... WHERE` per class of change).

### 4.3 Scope rules
- iot_staff: `tenant_id = principal.tenant_id`. cloud_staff: optional `tenant_id` filter. house_owner:
  `house_id IN principal.house_ids` and only GET endpoints (403 on writes).
- Every repository method takes a `Scope` object; tests prove cross-tenant access returns 404.

---
## 5. Code structure (files to create)
```
app/api/{houses.py, rooms.py, feeds.py, ingest.py, clips.py, health.py}
app/schemas/{house.py, room.py, feed.py, clip.py}
app/services/{house_service.py, feed_service.py, feed_config_versioning.py, ingest_service.py, clip_library_service.py, connectivity.py}
app/repositories/{house_repo.py, room_repo.py, feed_repo.py, feed_version_repo.py, media_event_repo.py}
app/gateways/s3_media_gateway.py      # put_object, delete_object, presign_get
app/jobs/connectivity_monitor.py
app/models/orm.py
scripts/device_sim.py (repo root scripts/)  # --feed-id --interval 20 --clips demo_clips/*.wav --token-client device-uploader
```

---
## 6. UI (feature folder `c1-iot`) — D2 wireframe "Camera Feed Manager"
| Page | Key elements | API |
|---|---|---|
| **Camera Feed Manager** `/iot/feeds` | FilterBar (house, room, kind, status), "+ Add feed" opens FormPanel (name, kind, house, room, interval 5–3600, sensitivity, network label; note "connectivity is recorded, not measured"), DataTable (Name, Room, Kind, Status chip, Connectivity dot+label+age, Enabled), row click → detail | `GET /houses`, `GET /houses/{id}/rooms`, `GET/POST /feeds` |
| **Feed Detail** `/iot/feeds/:id` | Header with status chips; ActionBar: Enable/Disable (disabled with tooltip if no room), Edit config, Archive (confirm); Config form; Versions table with Restore; **Upload clip** card (file + captured_at default now + optional client id) for the demo; Recent clips with ClipPlayer and clip status | feed endpoints, `POST /ingest/clip`, `GET /clips?feed_id=` |
| **Houses and Rooms** `/iot/houses` | Houses table (+ add/edit/delete with 409 messages); expandable rooms list with add/rename/delete | house/room endpoints |
| **Clip Library** `/iot/clips`, `/home/clips` | FilterBar (house, feed, status, date range); table (time, feed, room, kind, size, status, top label); play button | `GET /clips`, playback URL |
| **My Feeds** `/home/feeds` | Read-only feed cards for the owner's houses with connectivity | `GET /feeds` |
States: loading skeleton, empty ("No feeds yet — Add feed"), 409/422 shown inline, success toasts.

---
## 7. Tests (pytest)
Unit: S3 key builder; ingest decision order (mock repos/gateway) incl. compensation; connectivity derive
(table-driven, all rows); config versioning (n+1, restore copies values); scope filter builder.
API: CRUD happy paths; `DELETE /houses` 409; `DELETE /rooms` 409; enable without room 409; ingest 201 →
document in Mongo + object in LocalStack S3; duplicate `client_clip_id` → 200 duplicate; kind mismatch 422;
oversize 413; disabled feed 409; owner cannot POST (403); tenant B cannot see tenant A feed (404);
playback URL returns presigned URL; `GET /feeds/stats` counts. Target coverage ≥ 75%.

---
## 8. Task list (do in order; each ≈ ½–1 day)
| ID | Task | Depends |
|---|---|---|
| C1-01 | Service skeleton, settings, health, Alembic baseline, Dockerfile (P0-6) | P0-3 |
| C1-02 | Migration `0001_initial` (§2.1) + ORM models + Mongo `ensure_indexes()` | C1-01 |
| C1-03 | Houses + rooms repositories, services, routers, schemas, tests | C1-02, P0-4 |
| C1-04 | Feeds CRUD, status endpoint, archive, scope rules, tests | C1-03 |
| C1-05 | Config versioning (PUT config, list, restore), tests | C1-04 |
| C1-06 | S3 gateway (LocalStack) + `POST /ingest/clip` full decision table + compensation, tests | C1-04 |
| C1-07 | Clips list/detail/playback-url, tests | C1-06 |
| C1-08 | ConnectivityMonitor job + `GET /feeds/stats`, tests | C1-06 |
| C1-09 | `scripts/device_sim.py` (service token, loops over demo clips, prints responses) | C1-06 |
| C1-10 | Seed: houses/rooms/feeds with fixed IDs (in `scripts/seed.py`) | C1-04 |
| C1-11 | UI: api/c1.ts + Camera Feed Manager + Add feed panel | C1-04, P0-8 |
| C1-12 | UI: Feed Detail (actions, config, versions, upload, recent clips) | C1-05..07 |
| C1-13 | UI: Houses and Rooms, Clip Library, My Feeds | C1-07 |
| C1-14 | Playwright `e2e/c1-feed-setup.spec.ts` (demo rehearsal) | C1-11..13 |
| C1-15 | Deploy on EC2, verify with real S3; demo prep and video | infra §8 |

## 9. Acceptance checklist
- [ ] All endpoints in §3 exist, documented in `/api/v1/docs/c1`, and follow the envelope.
- [ ] Ingest is exactly-once (duplicate client id) and leaves no orphan object on DB failure (test proves it).
- [ ] Feed state machine and connectivity behave per §4 (device simulator start/stop shows online→offline).
- [ ] Owners are read-only and isolated; tenant isolation test passes.
- [ ] C3 worker picks up clips uploaded by C1 (integration test I-1 in doc 05).
- [ ] UI pages in §6 work on EC2 with real S3.

---
## 10. Deliverable #3 demo (C1)
### 10.1 Live demo (≈ 7 min) — rubric "complete implementation with UI and backend" (3 pts)
1. Log in as `iot@acme.test` → lands on **Camera Feed Manager** (role routing).
2. **Houses and Rooms**: add house "Elm Ct" (timezone) and two rooms; try deleting a room with a feed → 409 message.
3. **Add feed** "Hall Mic" (audio) without a room → appears `provisioned`, Enable disabled with tooltip; call
   enable anyway via Swagger → `409 room_required`. Assign room → Enable.
4. **Config versioning**: change interval 30 → 10 (v2), restore v1 (v3), show version table.
5. **Ingest**: upload `glass_break.wav` in Feed Detail → `queued` → (if C3 running) becomes `analyzed` with top
   label. Show the S3 object in the AWS console under the tenant/house/feed prefix and the record in Clip Library.
6. Edge cases: upload an mp4 to an audio feed → 422; upload with the same client id twice → `duplicate:true`.
7. **Connectivity**: run `scripts/device_sim.py --interval 5` → feed `active/online`; stop it → after the
   interval the monitor flips it to `inactive/offline`.
8. Log in as `owner.maple@acme.test` → **My Feeds** read-only, **Clip Library** plays a clip; owner of Oak cannot see Maple.
9. **Unit demo**: run `make test-c1` (show passing tests + coverage) and open `/api/v1/docs/c1`.
### 10.2 Scenario video (≈ 5 min) — "IoT staff onboard a new room sensor" (2 pts)
Record steps 1–5 and 7–8 as one story with narration: *new resident's house → add room → register feed →
configure → enable → first clip arrives → feed goes online → owner sees it*. Show the URL bar (EC2 host) to
prove it is deployed. Rehearse with the Playwright spec first.
### 10.3 Prep checklist
EC2 up, seed run, demo clips present, device simulator token minted, AWS console tab open on the S3 prefix,
a backup local stack ready if the network fails.
