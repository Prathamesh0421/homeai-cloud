# C3 — System Database Management (incl. AI inference) — Implementation Plan
**Owner:** Renuka Prasad Patwari · **Service:** `services/c3_data` (API port 8003) + `c3-worker` (same image)
**UI:** `web/src/features/c3-data` · **Reads first:** `AGENTS.md`, `docs/01`–`04`. Design: D2 Part III (C3).

## 0. Goal in one line
Run the YAMNet inference pipeline (claim → classify → label map → store → hand off to C2) reliably, **manage
model versions (register, evaluate, activate, roll back) through a UI, show the model deployment live**, and
provide scoped record browsing, the data dictionary, integrity checks, activity patterns, seed and backups.

> **Deliverable #3 note — C3 is the AI component.** Graders expect: (1) UI, (2) **model management**,
> (3) **deployment**. §3.1, §6 and §10 are built around those three.

---
## 1. Scope
**In:** inference worker, `ClassificationPipeline`, YAMNet runner, label mapper, AI detections, activity
patterns, **model registry + evaluation + activation [D3 addition]**, **test-classify endpoint [D3 addition]**,
**deployment status endpoint + worker heartbeats [D3 addition]**, `GET /detections/stats` **[D3 addition]**,
re-classify, requeue, records browsing, data dictionary, integrity checks, nightly backup, C3 UI pages.
**Out:** clip upload (C1), alert decisions (C2), dashboards (C4).

### 1.1 Dependencies
| Needs | From | Stub until ready |
|---|---|---|
| `media_events` queued docs + S3 objects | C1 (`POST /ingest/clip`) | `scripts/demo/c3_enqueue.py` (DEMO_MODE): uploads a demo clip to S3 and inserts a queued doc |
| `POST /alerts/evaluate` | C2 | `HANDOFF_MODE=log` setting: log payload instead of calling C2 |
| JWT/JWKS + service token `alerts:evaluate` | C4 | test keys |
| Read-only roles on c1, c2, c4 and Mongo collections | infra `init.sql` / `init.js` | — |
| **Provides** | **To** | |
| `ai_detections` (contract 02 §4.2) | C2 (reads) | |
| `GET /records/*`, `GET /detections/stats`, `GET /activity-patterns` | C4 dashboards, Home Overview | |

---
## 2. Data model
### 2.1 PostgreSQL schema `c3`
```sql
CREATE TABLE c3.ml_models (
  model_id     UUID PRIMARY KEY,
  name         VARCHAR(40) NOT NULL,                 -- 'yamnet'
  version      VARCHAR(20) NOT NULL,                 -- semver '1.0.0', '1.1.0'
  framework    VARCHAR(20) NOT NULL DEFAULT 'tensorflow',
  source       VARCHAR(10) NOT NULL CHECK (source IN ('bundled','s3')),   -- bundled = YAMNet in image
  artifact_uri TEXT,                                  -- s3://bucket/models/yamnet/1.1.0/ when source = s3
  label_map    JSONB NOT NULL,                        -- {version, entries:[{home_label, category, source_classes[], min_confidence, rule}]}
  status       VARCHAR(10) NOT NULL CHECK (status IN ('registered','evaluated','active','retired')),
  metrics      JSONB,                                 -- last evaluation (see §4.4)
  notes        TEXT,
  created_by   UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  activated_by UUID, activated_at TIMESTAMPTZ,
  UNIQUE (name, version)
);
CREATE UNIQUE INDEX ux_one_active ON c3.ml_models ((status)) WHERE status = 'active';

CREATE TABLE c3.model_evaluations (
  evaluation_id UUID PRIMARY KEY, model_id UUID NOT NULL REFERENCES c3.ml_models(model_id),
  dataset       VARCHAR(60) NOT NULL,                 -- 'eval-v1'
  metrics       JSONB NOT NULL, started_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ, created_by UUID NOT NULL
);
CREATE TABLE c3.integrity_reports (
  report_id UUID PRIMARY KEY, requested_by UUID, scope JSONB NOT NULL,
  status VARCHAR(8) NOT NULL CHECK (status IN ('running','done','failed')),
  findings JSONB NOT NULL DEFAULT '[]', started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX ux_one_running ON c3.integrity_reports ((scope->>'tenant_id')) WHERE status = 'running';
CREATE TABLE c3.data_dictionary_versions (
  version VARCHAR(20) PRIMARY KEY, document JSONB NOT NULL, published_by UUID NOT NULL, published_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
### 2.2 MongoDB (owner C3)
- `ai_detections` — contract 02 §4.2. Indexes: `{media_id:1}` unique, `{house_id:1, detected_at:-1}`,
  `{house_id:1, top_label:1, detected_at:-1}`, `{tenant_id:1, detected_at:-1}`.
- `activity_patterns` — `{_id:"<house>:<room>:<yyyy-mm-dd>", tenant_id, house_id, room_id, date, hours:[24 ints],
  baseline_mean:[24], baseline_std:[24], anomaly_score, last_activity_at}`. Index `{house_id:1, room_id:1, date:-1}`.
- `worker_heartbeats` **[D3]** — `{_id: worker_id, hostname, model_id, model_version, started_at, last_heartbeat,
  processed, failed, avg_latency_ms}`; TTL index on `last_heartbeat` (10 min).
- C3 also updates C1's `media_events` processing fields only (`status, attempts, claimed_at, worker_id, error,
  detection_id, handoff_status`).

### 2.3 Default label map (model `yamnet 1.0.0`, seeded active) — must match YAMNet class display names exactly
| home_label | category | source_classes | min | rule |
|---|---|---|---|---|
| smoke_alarm | emergency | "Smoke detector, smoke alarm", "Fire alarm", "Alarm", "Beep, bleep" | 0.50 | max |
| distress_sound | emergency | "Screaming", "Shout", "Yell", "Crying, sobbing", "Baby cry, infant cry" | 0.60 | consec2 |
| glass_break | security | "Glass", "Shatter", "Breaking" | 0.55 | max |
| fall_indicator | safety | "Thump, thud", "Bang", "Slam" | 0.65 | consec2 |
| cough | wellness | "Cough", "Throat clearing" | 0.55 | mean |
| speech | wellness | "Speech", "Conversation" | 0.50 | mean |
| dog | wellness | "Dog", "Bark" | 0.55 | max |
Validate every class name against YAMNet's `yamnet_class_map.csv` on register/update (422 with unknown names).

---
## 3. API (all under `/api/v1`)
Access: **CS** cloud_staff, **IS** iot_staff, **O** house_owner, **svc** service scope.
### 3.1 Model management and deployment **[D3 additions — the AI deliverable]**
| Method & path | Access | Request | Response / rules |
|---|---|---|---|
| `GET /models` | CS | `name?`, `status?` | list `{model_id, name, version, status, source, metrics.summary, created_at, activated_at}` |
| `GET /models/active` | CS, IS, svc | — | active model with label map |
| `GET /models/{id}` | CS | — | full record + evaluations |
| `GET /models/classes` | CS | `q?` | YAMNet 521 class names (for the label-map editor autocomplete) |
| `POST /models` | CS | `{name:"yamnet", version, base_model_id?, label_map?, notes?}` — clones label map from `base_model_id` (default active) when omitted | 201 status `registered`; 409 duplicate version; 422 invalid label map |
| `POST /models/{id}/artifact` | CS | multipart `.zip` of a TF SavedModel ≤ 200 MB | uploads to `s3://.../models/{name}/{version}/`, sets `source=s3`; optional (stretch) |
| `PUT /models/{id}/label-map` | CS | label map JSON | 409 `model_active` if active (create a new version instead); status back to `registered` |
| `POST /models/{id}/evaluate` | CS | `{dataset:"eval-v1"}` | runs evaluation (§4.4) synchronously (≤ 60 s for ~30 clips); stores metrics; status `evaluated`; 200 metrics |
| `POST /models/{id}/activate` | CS | `{confirm:true}` | requires status `evaluated` or `retired` (422 otherwise); previous active → `retired`; transaction; workers switch within 10 s |
| `POST /models/{id}/retire` | CS | — | 409 if active |
| `GET /models/deployment` | CS | — | `{active_model:{id,version}, workers:[heartbeat docs], queue:{queued, processing, failed, analyzed_last_hour}, throughput_per_min, p95_latency_ms}` |
| `POST /inference/test` | CS, IS | multipart `file` (≤ 20 MB), `model_id?` | **no persistence**: `{model, top_label, top_confidence, labels[], raw_top10:[{class, score}], frames, duration_s, latency_ms}` |

### 3.2 Inference and records (from D2)
| Method & path | Access | Request | Response / rules |
|---|---|---|---|
| `POST /inference/classify` | CS | `{media_id, force?}` | re-run pipeline for a stored clip; 409 `already_analyzed` unless force; 200 detection + `alert_decision` |
| `POST /media-events/{media_id}/requeue` | CS | — | only `failed` (409 `not_failed`); `status=queued, attempts=0, error=null` |
| `GET /records/{entity}` | role-scoped (§4.6) | `house_id, from, to, filter=field:value, page, page_size` | entities: `houses, rooms, feeds, clips, detections, alerts, activity_patterns`; 404 `unknown_entity`; 429 > 60/min/user |
| `GET /records/{entity}/{id}` | role-scoped | — | one record |
| `GET /detections/stats` **[D3]** | CS, O, svc `records:read` | `group_by=top_label|day|house`, `from`, `to`, `house_id`, `tenant_id` | contract 02 §4.6 |
| `GET /activity-patterns` | O (own), CS | `house_id`, `room_id?`, `date` (default today) or `days=7` | patterns |
| `GET /data-dictionary` | CS | `entity?`, `version?`, `format=json|csv` | latest or given version; CSV download |
| `GET /data-dictionary/versions` | CS | — | list |
| `POST /data-dictionary` | CS | `{version, document}` or `{version, generate:true}` | publishes a new immutable version (generate = build from live schemas, §4.7) |
| `POST /integrity-checks` | CS | `{tenant_id?, house_id?}` | 202 `{report_id}`; 409 `check_running` |
| `GET /integrity-reports` / `GET /integrity-reports/{id}` | CS | — | list / detail with findings |

---
## 4. Business logic
### 4.1 Worker loop (`python -m app.worker`)
```text
on start: worker_id = hostname-pid; load active model (cache); heartbeat thread every 10 s
loop:
  if active model id changed (checked every 10 s): load new model + label map; update heartbeat
  ev = media_events.find_one_and_update(
         {"$or":[{"status":"queued"},{"status":"processing","claimed_at":{"$lt": now-120s}}]},
         {"$set":{"status":"processing","claimed_at":now,"worker_id":wid},"$inc":{"attempts":1}},
         sort=[("uploaded_at",1)], return_document=AFTER)
  if not ev: sleep 2 s; continue
  try: pipeline.classify(ev)
  except Exception as e:
       media_events.update(ev._id, status = "queued" if ev.attempts < 3 else "failed", error=str(e)[:500])
```
Run 1 worker by default; `docker compose up -d --scale c3-worker=2` must be safe (atomic claim).

### 4.2 `ClassificationPipeline.classify(ev, force=False, model=None)`
1. If a detection exists for `media_id` and not `force` → 409 (API path) / worker path: the detection was stored by an earlier attempt that failed later, so re-send the handoff and mark the clip analyzed (`finish_existing`).
2. `bytes = s3.get_object(ev.s3.key)`; decode with ffmpeg to 16 kHz mono float32 (`ffmpeg -i pipe:0 -ac 1 -ar 16000 -f f32le pipe:1`); clip to 30 s; reject empty (422 `unreadable_clip`).
3. `scores = yamnet(waveform)` → shape `(frames, 521)`; frame `i` covers `[0.48·i, 0.48·i + 0.96]` s.
4. `labels = LabelMapper.apply(scores, label_map)`:
   per entry: `per_frame = max(scores[:, idx] for idx in entry.source_class_indices)`;
   `max` → max(per_frame); `mean` → mean(per_frame); `consec2` → max over i of min(per_frame[i], per_frame[i+1])
   (single frame → that frame); keep if ≥ `min_confidence`; record `source_class` (best class) and
   `start_s/end_s` of the best frame(s). Sort by confidence desc.
5. Build detection (UUID, tenant/house/room from `ev`, model id/name/version, labels, top label or `"none"`).
6. Upsert `ai_detections` by `media_id` (force replaces, keeping the detection's `_id`, so C2 answers `duplicate`); set `media_events.status=analyzed, detection_id`.
7. `ActivityPatternService.rollup(detection)` (§4.5).
8. Handoff (§4.3). Record latency in heartbeat stats.

### 4.3 Handoff to C2 (`AlertHandoffClient`)
POST contract 02 §4.3 with service token (`c3-worker`, scope `alerts:evaluate`). Retry on 5xx/timeout 3 times
(2/4/8 s). Success → `handoff_status=done`; failure → `pending`. The integrity job re-sends `pending` ones
(C2 is idempotent on `detection_id`). `HANDOFF_MODE=log` for independent development.

### 4.4 Model evaluation
Dataset `eval-v1`: `s3://<bucket>/models/eval/eval-v1/manifest.json` = `[{"file":"glass_break_01.wav","expected":"glass_break"}, ..., {"file":"silence_01.wav","expected":"none"}]`
(~30 clips: 4 per label + 2 silence, from ESC-50 / generated; uploaded by `scripts/upload_eval_set.py`).
For each clip: run steps 2–4 with the candidate label map; predicted = top label or `none`.
Metrics: `accuracy`, per-label `precision`, `recall`, `f1`, `support`, `confusion` (8×8 incl. none),
`avg_latency_ms`, `p95_latency_ms`, `dataset`, `evaluated_at`. Store in `model_evaluations` and copy summary to `ml_models.metrics`.

### 4.5 Activity patterns and anomaly score
- Rollup: house timezone from `c1.houses` (reader); hour `h` = local hour of `detected_at`; `$inc hours.h`
  in the day document (upsert); `last_activity_at`.
- Nightly job (01:00 UTC): for each house/room, baseline = mean and std of `hours[h]` over the previous 28 days.
- `anomaly_score = mean_h min(1, |count_h − mean_h| / (3·std_h + 1))` computed on each rollup; bands:
  `< 0.30` normal, `0.30–0.60` unusual, `≥ 0.60` anomalous.

### 4.6 Records scope
| Entity | Source (read-only) | house_owner | iot_staff | cloud_staff |
|---|---|---|---|---|
| houses, rooms, feeds | `c1.*` | own houses | own tenant | all (`tenant_id` filter) |
| clips | `media_events` | own houses | own tenant | all |
| detections, activity_patterns | own Mongo | own houses | own tenant | all |
| alerts | `c2.alerts` | own houses | 403 | all |
Field filters only on a whitelist per entity (e.g. detections: `top_label`, `room_id`; clips: `status`, `feed_id`).
Never return `password_hash`/`secret_hash` (C4 tables are not browsable).

### 4.7 Data dictionary generation
`DataDictionaryService.generate()` reflects all four Postgres schemas (via reader role, `information_schema`)
and samples Mongo collections' declared schemas (`app/dictionary/mongo_schemas.py`), producing
`{version, generated_at, entities:[{name, store, owner_component, fields:[{name, type, nullable, description}]}]}`.
Descriptions come from `app/dictionary/descriptions.yaml` (hand-written, one line per field).

### 4.8 Integrity checks (async via `BackgroundTasks`; nightly 02:00 UTC for all tenants)
| Check | Severity | Auto-action |
|---|---|---|
| detection whose `media_id` not in `media_events` | high | — |
| `media_events.status=analyzed` without `detection_id` | medium | — (offer re-classify) |
| `c2.alerts.detection_id` not in `ai_detections` | high | — |
| `processing` older than 120 s | medium | requeue candidate |
| `failed` clips | medium | list for requeue |
| `handoff_status=pending` | low | re-send to C2 |

### 4.9 Backup (nightly 03:00 UTC, also `python -m app.jobs.backup` on demand)
`pg_dump -Fc` (via a dedicated `backup` role) and `mongodump --archive --gzip` → S3 `backups/<date>/`; keep 14
days (S3 lifecycle). Document restore commands in `services/c3_data/README.md`.

---
## 5. Code structure
```
app/main.py, app/worker.py
app/api/{models.py, inference.py, media_events.py, records.py, detections.py, activity.py, dictionary.py, integrity.py, health.py}
app/ml/{yamnet_runner.py (load bundled or s3 model, class map), audio.py (ffmpeg decode), label_mapper.py, evaluator.py, model_cache.py}
app/services/{classification_pipeline.py, model_registry.py, deployment_status.py, record_query.py, dictionary_service.py, integrity_service.py, activity_service.py}
app/repositories/{ml_model_repo.py, evaluation_repo.py, report_repo.py, dictionary_repo.py, detection_repo.py, media_event_repo.py, activity_repo.py, heartbeat_repo.py}
app/gateways/{s3_gateway.py, store_readers.py, alert_handoff_client.py, house_reader.py}
app/jobs/{baseline_job.py, integrity_nightly.py, backup.py}
app/dictionary/{mongo_schemas.py, descriptions.yaml}
scripts/download_yamnet.py (image build), scripts/upload_eval_set.py, scripts/demo/c3_enqueue.py
```
YAMNet loading: `hub.load("/models/yamnet/1")` (downloaded at build from TF Hub/Kaggle `google/yamnet/tensorFlow2/yamnet/1`);
class names from `model.class_map_path()`. Warm up once at start (inference on 1 s of zeros). Keep the
model in a process-level cache keyed by `model_id`; label map changes need no TF reload.

---
## 6. UI (feature folder `c3-data`)
| Page | Key elements | API |
|---|---|---|
| **Model Management** `/ops/models` | **Deployment panel** at top: active model + version, workers (id, host, model version, last heartbeat age, processed, avg latency), queue depth (queued/processing/failed), throughput — auto-refresh 5 s. Versions table (version, status chip, accuracy, macro-F1, created, activated) with actions: New version (clone), Evaluate, Activate (confirm dialog showing metric diff vs active), Roll back (activate previous), Retire | `/models`, `/models/deployment` |
| **Model Detail** `/ops/models/:id` | Label-map editor: one row per home label — source classes (multi-select with autocomplete from `/models/classes`), threshold slider 0–1, frame rule select; Save (disabled for active); Metrics: accuracy, per-label P/R/F1 table, confusion matrix grid, latency; evaluation history | `/models/{id}`, `PUT label-map`, `evaluate` |
| **Test Classify** `/ops/classify` | Upload a clip (or pick a demo clip), choose model version (default active); result: ConfidenceBars for home labels with thresholds, raw YAMNet top-10, duration, frames, latency; "Compare with active" runs both | `POST /inference/test` |
| **Database Records** `/ops/records` | Entity chips, FilterBar (tenant, house, date range, field filter), DataTable with scope note, row drawer with JSON; actions: Re-classify (clips/detections), Requeue (failed clips) | `/records/*`, classify, requeue |
| **Data Dictionary** `/ops/dictionary` | Version select, entity list grouped by owner component, fields table; Generate new version; Export JSON/CSV | dictionary endpoints |
| **Integrity** `/ops/integrity` | Run check (202 → polling every 5 s), reports list, findings with severity icon + word, links to records, bulk requeue | integrity endpoints |
| **Activity** `/ops/activity` (+ widget used by C4 Home Overview) | House/room picker, 24-hour bar chart vs baseline band, anomaly score badge, 7-day heatmap | `/activity-patterns` |

---
## 7. Tests
Unit: label mapper (synthetic score matrices for max/mean/consec2, threshold edges, empty result → `none`);
audio decode (wav/mp3/mp4 fixtures, 1 s each); evaluator metrics (precision/recall/confusion on a fixed
prediction list); anomaly score formula; scope filters; label map validation against class list.
Integration: worker claims atomically with 2 threads (each clip processed once); retry to `failed` after 3;
visibility timeout reclaim; handoff retry → `pending` → integrity re-send; activate switches the single
active row and worker reloads (fake runner); records scope (owner/iot/cloud, tenant isolation); integrity
findings on seeded broken fixtures; dictionary generate contains all 4 schemas.
Slow (marked `@pytest.mark.slow`, run before demos): real YAMNet on demo clips — `glass_break.wav` → `glass_break`,
`dog.wav` → `dog`, `silence.wav` → `none`.

---
## 8. Task list
| ID | Task | Depends |
|---|---|---|
| C3-01 | Skeleton (API + worker entrypoint), settings, health, Alembic, Dockerfile with ffmpeg + TF + YAMNet download | P0-3 |
| C3-02 | Migrations (§2.1), Mongo indexes + TTL, seed active model `yamnet 1.0.0` | C3-01 |
| C3-03 | `audio.py` decode + `yamnet_runner.py` + warm-up; unit tests | C3-01 |
| C3-04 | `label_mapper.py` + label-map validation vs class map; unit tests | C3-03 |
| C3-05 | `ClassificationPipeline` + detection repo; `POST /inference/test` | C3-04 |
| C3-06 | Worker loop: atomic claim, retry/fail, visibility timeout, heartbeats; concurrency tests | C3-05, C1-06 (or `c3_enqueue.py`) |
| C3-07 | Model registry API: list/get/classes/create/label-map/retire; tests | C3-02, C3-04 |
| C3-08 | Evaluator + eval set upload script + `POST /models/{id}/evaluate`; activation + worker hot reload; `/models/deployment` | C3-07, C3-06 |
| C3-09 | `AlertHandoffClient` (service token, retries, pending) + `POST /inference/classify`; integration with C2 | C3-06, C2-07 |
| C3-10 | Records API with scope + rate limit; `GET /detections/stats` | C3-02 |
| C3-11 | Activity rollup + baseline job + `/activity-patterns` | C3-09 |
| C3-12 | Integrity service (async + nightly) + requeue endpoint | C3-09 |
| C3-13 | Data dictionary generate/publish/export | C3-10 |
| C3-14 | Backup job + restore doc | C3-02 |
| C3-15 | UI: api/c3.ts, Model Management with Deployment panel | C3-08, P0-8 |
| C3-16 | UI: Model Detail (label-map editor, metrics, confusion matrix) | C3-08 |
| C3-17 | UI: Test Classify | C3-05 |
| C3-18 | UI: Database Records, Data Dictionary, Integrity, Activity | C3-10..13 |
| C3-19 | EC2 deployment: image build on host, scale workers, verify real S3; Playwright `e2e/c3-model-activate.spec.ts` | infra §8 |
| C3-20 | Demo prep + video | all |

## 9. Acceptance checklist
- [ ] Every uploaded clip ends `analyzed` (or `failed` after 3 attempts) and C2 receives exactly one evaluate per detection.
- [ ] Two workers never process the same clip (test + live scale demo).
- [ ] A new model version can be created, edited, evaluated, activated and rolled back from the UI; workers report the new version within 10 s.
- [ ] Test Classify returns labels for demo clips with the selected version.
- [ ] Records are scoped per role/tenant; integrity report finds seeded faults; dictionary covers all stores.
- [ ] Nightly backup object appears in S3.

---
## 10. Deliverable #3 demo (C3) — UI + model management + deployment
### 10.1 Live demo (≈ 8 min)
1. **Deployment**: on EC2 show `docker compose ps` (c3-data, c3-worker), then **Model Management** deployment
   panel: active `yamnet 1.0.0`, one worker heartbeating, queue empty.
2. **Pipeline**: upload `glass_break.wav` (C1 UI or `c3_enqueue.py`) → queue shows 1 → worker processes → record
   appears in **Database Records › detections** (top label, confidence, model version) → C2 alert decision shown.
3. **Test Classify**: upload `dog.wav` and `thud.wav`; show home labels vs thresholds and raw YAMNet top-10.
4. **Model management**: create version `1.1.0` from active; in the label-map editor lower `fall_indicator` to 0.55
   and add "Knock" to its classes; **Evaluate** → metrics + confusion matrix; compare with 1.0.0; **Activate** →
   deployment panel shows worker on 1.1.0 within 10 s; re-run Test Classify on `thud.wav` → now detected;
   **Roll back** to 1.0.0.
5. **Scale**: `docker compose up -d --scale c3-worker=2`, upload 6 clips with `device_sim.py` → both workers
   process, no clip twice (records show distinct worker ids).
6. **Data management**: Records scope (log in as owner → sees only own detections), Data Dictionary export,
   Integrity check finds a planted orphan; requeue a failed clip; Activity chart for Maple Kitchen.
7. Unit demo: `make test-c3` (and the slow YAMNet test), Swagger `/api/v1/docs/c3`.
### 10.2 Scenario video (≈ 5–6 min) — "Tuning the fall detector"
Ops notices missed falls (thuds) → tests a thud clip (not detected) → creates model v1.1.0 with a tuned label
map → evaluates (better recall, precision shown) → activates → live worker switches → the next uploaded
thud is classified `fall_indicator` and C2 raises a fall alert → roll-back option shown.
### 10.3 Prep
Upload eval set to S3, pre-build the C3 image on EC2 (TF download takes minutes), warm the model, keep a
planted orphan for the integrity demo, have `c3_enqueue.py` as fallback if C1 is down.
