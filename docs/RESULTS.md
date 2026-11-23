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
| c1-iot (1 of 2) |  |  |  |  |
| c2-alerts (1 of 2) |  |  |  |  |
| c3-data (1 of 2) |  |  |  |  |
| c3-worker (1 of 2) |  |  |  |  |
| c4-dashboard (1 of 2) |  |  |  |  |

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
