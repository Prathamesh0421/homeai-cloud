# C1 demo runbook — Home-Based IoT Device Manager (Ekant)

The script is the C1 plan §10.1; this page is how to run it on the EC2 demo host, step by step.
Rubric (06 §4): every C1 function through the UI, backend proof, edge cases, unit tests, on EC2.

**URL** http://44.226.166.194 · **Swagger** http://44.226.166.194/api/v1/docs/c1
**Logins** (password `Demo!2026`): `iot@acme.test` (IoT staff: Camera Feeds, Houses, Clips) ·
`owner.maple@acme.test` (Maple owner: My Feeds, Clip Library) · `owner.oak@acme.test` (isolation).
**Seed feeds** (`scripts/seed_ids.py`): Maple Kitchen Mic `…00a101` · Front Door Cam `…00a102` ·
Garage Cam `…00a103` (inactive) · Nursery Mic `…00a104` (no room) · Bathroom Mic `…00a105` ·
Oak Kitchen Mic `…00a201` · Pine Kitchen Mic `…00b101` (all `66666666-0000-0000-0000-…`).

Commands marked **EC2** run on the host in `~/homeai-cloud`.

## 0. Deploy (once, after the C1 PRs are merged)
| | Step | How |
|---|---|---|
| ☐ | Pull | **EC2** `git pull` |
| ☐ | New `.env` (adds `DATABASE_URL_C1`, `MONGO_URL_C1`) | **EC2** `RDS_ENDPOINT=… TEAM=… SITE_ADDRESS=:80 make deploy-env > .env` (same values as the last deploy) |
| ☐ | Build + start (adds `--profile c1` automatically) | **EC2** `make deploy` |
| ☐ | Seed C1 (houses, rooms, feeds; idempotent) | **EC2** `make seed-c1-docker` |
| ☐ | C1 healthy | `curl http://44.226.166.194/api/v1/health/c1` → `"status":"ok","db":"ok","mongo":"ok"` |
| ☐ | C2 stops answering 503 on c1 | Alert Rules → New rule for Maple → 201 |
| ☐ | Memory | **EC2** `free -m` / `docker stats --no-stream`: C1 adds ~120 MB; on a t3.micro watch for OOM kills |

## 1. Before (day before, then 1 hour before)
| | Step | How |
|---|---|---|
| ☐ | Clean C1 data | **EC2** `make demo-c1-reset ARGS=--yes` (removes Elm Ct etc. from rehearsals; seed feeds back to v1) |
| ☐ | Demo clips on the laptop (UI upload) | `brew install ffmpeg && scripts/fetch_demo_clips.sh` → `demo_clips/glass_break.wav` …; plus any small `.mp4` for the 422 step |
| ☐ | Demo clips on the host (simulator) | `scp -r demo_clips homeai-ec2:~/homeai-cloud/` |
| ☐ | C3 worker running (for `analyzed` + top label) | **EC2** `docker compose … ps` shows `c3-worker` up; run Test Classify once to warm the model |
| ☐ | Tests green | laptop `make test-c1-full` (102 passed, ~94 %) |
| ☐ | Tabs | 1 `iot@acme.test` → Camera Feeds · 2 Swagger `/api/v1/docs/c1` (Authorize with the iot token) · 3 AWS console S3 → `tenants/11111111-…0001/houses/` · 4 terminal on EC2 · 5 private window for `owner.maple` |
| ☐ | Rehearsed twice | this page, top to bottom, `make demo-c1-reset ARGS=--yes` after each |

## 2. Live demo (~8 min; timings from 06 §4.1)
**0:00–0:30 · Where C1 sits.** Devices → C1 (houses, rooms, feeds, versioned config) → clip to S3 +
`media_events` (queued) → C3 classifies → C2 alerts. C1 owns schema `c1`, the `media_events`
collection and the S3 clip prefix; C2/C3/C4 only read through grants or C1's API.

**0:30–1:30 · Houses and Rooms (tab 1, `iot@acme.test`).**
1. Login lands on **Camera Feed Manager** (role routing). Point out statuses and connectivity.
2. **Houses & rooms** → Add house **Elm Ct**, timezone `America/Chicago` → add rooms **Living Room**
   (living) and **Hallway** (entry).
3. Maple → delete room **Kitchen** → `409 room_in_use` (Kitchen Mic is in it).

**1:30–3:00 · Feed lifecycle.**
4. **+ Add feed** → **Hall Mic**, audio, house Elm Ct, **no room**, interval 30, medium → appears
   `provisioned`, disabled; **Enable** is greyed out with a tooltip.
5. Swagger: `PATCH /api/v1/feeds/{id}/status` `{"is_enabled": true}` → `409 room_required`.
6. Feed Detail → Room **Hallway** → Save → **Enable** → enabled.
7. **Config versioning**: Edit config interval 30 → **10** (v2); versions table → **Restore v1** (v3, 30 s).

**3:00–4:30 · Ingest.**
8. Feed Detail → **Upload clip** `glass_break.wav` (captured at = now, client id `hall-1840`) →
   `queued`; refresh → `analyzed` with top label (C3). Clip Library shows it; ▶ plays it.
9. AWS console tab: the object under `tenants/…/houses/<Elm Ct>/feeds/<Hall Mic>/yyyy/mm/dd/`.

**4:30–5:45 · Edge cases.**
10. Upload an `.mp4` to Hall Mic (audio) → `422 media_kind_mismatch`.
11. Upload `glass_break.wav` again with client id `hall-1840` → `duplicate: true`, no second clip.
12. Disable Hall Mic → upload → `409 feed_not_enabled`; enable again.

**5:45–6:45 · Connectivity (the monitor runs every 10 s on EC2).**
13. **EC2** `make demo-c1-sim ARGS="--feed-id <Hall Mic id> --interval 5"` → each upload prints
    `201`; Camera Feeds shows Hall Mic `active` / `online`.
14. Ctrl-C → within ~40 s (30 s capture interval + one monitor pass) Hall Mic is `inactive` / `offline`.

**6:45–7:30 · Owners and backend proof.**
15. Private window `owner.maple@acme.test` → **My Feeds** (read-only cards) → **Clip Library** ▶ plays.
    `owner.oak@acme.test` sees only Oak's Kitchen Mic (tenant/house isolation).
16. Laptop `make test-c1-full` (tests + coverage), Swagger `/api/v1/docs/c1`,
    **EC2** `docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml ps`.

## 3. If something breaks
| Symptom | Fallback |
|---|---|
| Clip stays `queued` | C3 worker down: show the `media_events` record in C3's Records page or Swagger `GET /clips/{id}`; `docker compose … restart c3-worker` |
| UI upload fails | Swagger `POST /api/v1/ingest/clip` with the same file |
| Simulator can't get a token | `SERVICE_CLIENT_SECRET_DEVICE` missing from `.env`: re-run `make deploy-env > .env`; or upload a few clips by hand to show online |
| `409 house_not_empty` when cleaning up | disable the house's feeds first (that is the rule) |
| EC2 down / network | local stack: `docker compose -f infra/docker-compose.yml --profile c1 up -d`, seeds (`make seed-c4-docker seed-c1-docker COMPOSE_PROD="docker compose -f infra/docker-compose.yml --profile c1"`), `make web` |
