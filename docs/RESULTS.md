# Results — scalability and load evidence (final project)

Fill these tables from the S-7 / S-8 / A-7 runs before the 2 Dec presentation.
Commands: `scripts/perf/clip_to_alert.py`, `scripts/perf/api_load.py` (see
`docs/05_INTEGRATION_AND_TESTING.md` §7 and `docs/08_FINAL_DELIVERABLES.md`).

## S-7 — API load (p50 / p95), 1 vs 2 copies

Host / layout: _TBD_ (e.g. single EC2 compose `--scale`, or ALB URL).  
Date: _TBD_ · Tool: `scripts/perf/api_load.py` · Notes: _TBD_

| Endpoint | Copies | Concurrency | Requests | p50 (ms) | p95 (ms) | Error rate |
|---|---|---|---|---|---|---|
| `GET /alerts` | 1 |  |  |  |  |  |
| `GET /alerts` | 2 |  |  |  |  |  |
| `POST /alerts/evaluate` | 1 |  |  |  |  |  |
| `POST /alerts/evaluate` | 2 |  |  |  |  |  |
| `GET /dashboard/summary` | 1 |  |  |  |  |  |
| `GET /dashboard/summary` | 2 |  |  |  |  |  |

### S-7 — Clip → alert stage timings (1 vs 2 workers)

Tool: `scripts/perf/clip_to_alert.py` · Clips / rate: _TBD_

| Stage | Workers | p50 (ms) | p95 (ms) | Notes |
|---|---|---|---|---|
| upload → queued | 1 |  |  |  |
| upload → queued | 2 |  |  |  |
| queued → analyzed | 1 |  |  |  |
| queued → analyzed | 2 |  |  |  |
| analyzed → decision | 1 |  |  |  |
| analyzed → decision | 2 |  |  |  |
| decision → email sent | 1 |  |  |  |
| decision → email sent | 2 |  |  |  |

## S-8 — Failover drill

Stop one copy of each service under load; record error rate and recovery.

| Service stopped | Load in flight | Client error rate | Recovery time | Notes / screenshot |
|---|---|---|---|---|
| c1-iot (1 of 2) | 10 clients, ~13–17k req / 40 s, `GET /feeds` and `POST /ingest/clip` | 0 % on a graceful stop; crash: GET 0 %, POST 5/12973 (0.04 %) | < 0.1 s | details below; `failover_drill.py` |
| c2-alerts (1 of 2) |  |  |  |  |
| c3-data (1 of 2) |  |  |  |  |
| c3-worker (1 of 2) |  |  |  |  |
| c4-dashboard (1 of 2) |  |  |  |  |

### S-8 — c1-iot detail (28 Nov 2026)

Host: MacBook (arm64), Docker Desktop, local stack with the scale override (S-1) and the Caddy
load-balancing block (S-2), **2 copies of every service**:
`docker compose -f infra/docker-compose.yml -f infra/docker-compose.scale.yml -f tests/integration/compose.handoff.yml --profile c1 --profile c3 --profile gateway up -d --build --scale c1-iot=2 --scale c2-alerts=2 --scale c3-data=2 --scale c3-worker=2 --scale c4-dashboard=2`.
Tool: `scripts/perf/failover_drill.py --service c1-iot [--ingest] [--kill]`: 10 clients through Caddy
(:8080) for 40 s; at t = 10 s one copy is stopped (`docker stop -t 10`, SIGTERM then drain) or
crashed (`docker kill`); started again afterwards. Error = HTTP 5xx or failed request.
`POST /ingest/clip` repeats one `client_clip_id` (device uploader token), so after the first
upload each POST is a `duplicate: true` answer (auth, feed lookup, Mongo lookup, 192 KB body).

| Load | Stop | Requests | Errors | Recovery | p50 / p95 ms before → after |
|---|---|---|---|---|---|
| `GET /feeds` (IoT staff) | `docker stop` | 16 311 | 0 | 0 s | 16 / 32 → 23 / 49 |
| `GET /feeds` (IoT staff) | `docker kill` | 17 609 | 0 | 0 s | 14 / 28 → 23 / 47 |
| `POST /ingest/clip` (device) | `docker stop` | 12 967 | 0 | 0 s | 22 / 42 → 28 / 59 |
| `POST /ingest/clip` (device) | `docker kill` | 12 973 | 5 × 502 (0.04 %) | 0.04 s | 19 / 37 → 29 / 69 |

Reading: a graceful stop (rolling deploy, scale-in) loses nothing: uvicorn finishes in-flight
requests and Caddy sends new ones to the other copy. A crash loses only the POSTs that were in
flight on the crashed copy (5 of 10 clients' current requests); a gateway must not retry those,
since the copy may have processed them. Devices retry with the same `client_clip_id`, which C1
answers `duplicate: true` without storing the clip twice. GETs on a dropped keep-alive
connection are retried by the HTTP client itself. Latency rises after the stop because one copy
then serves everything.

Same crash drills with `main`'s Caddyfile (plain `reverse_proxy c1-iot:8001`, hot-reloaded):
GET 0/13 955, POST 5/12 740 (0.1 s). Locally the gateway's retry makes no measurable difference:
Docker drops a stopped copy from its DNS at once, and both configurations spread load evenly
(5 s sample: 1334/1216 requests per copy plain, 1605/1621 with `least_conn`). S-2's retry and
passive health matter where a dead target stays listed for a while (the 5 s DNS refresh, an
ALB target before deregistration) or a copy refuses connections without being removed.

## A-7 — Auto Scaling scale-out

API ASG target CPU 60 %; worker ASG on queued-clip metric (fallback CPU).  
ALB URL: _TBD_ · Date: _TBD_

| ASG | Trigger | Min → observed max | Time to healthy target | Evidence |
|---|---|---|---|---|
| API | `api_load.py` / CPU |  |  | console screenshot |
| Worker | backlog / CPU |  |  | CloudWatch metric |

## Screenshots / artifacts

- [ ] ALB target health
- [ ] ASG activity history
- [ ] CloudWatch dashboard
- [ ] Perf CSV / logs attached or linked
