# Contract and design changelog

Record every change to `02_CONTRACTS.md`, a component's API section, or a D2 design decision.
Format: `YYYY-MM-DD — <component(s)> — <change> — agreed by <names>`.

## Baseline (Deliverable #3 plan, 2026-11-02)
Additions to the D2 design made by this plan (all marked **[D3 addition]** in the component plans):
- C1: `GET /feeds/stats` for C4 dashboards; `device-uploader` service client; `house_id` accepted on `POST /houses` only in DEMO_MODE (fixed seed IDs).
- C2: `POST /alert-rules/defaults`, `POST /alert-rules/subscriptions/sync`, ContactSubscriptionSync job, `trigger_label` column on `alert_types`, `next_attempt_at` on `notifications`, DEMO_MODE `view_link` in alert detail; `GET /alerts` also accepts service scope `alerts:read`.
- C3: model registry (`/models*`, `model_evaluations` table, model status), `POST /inference/test`, `GET /models/deployment` + `worker_heartbeats`, `GET /detections/stats`, `handoff_status` field; max worker attempts fixed at 3.
- C4: `GET /auth/revoked`, `POST /dashboard/rollup`, `users_public` view, service clients table.
- Platform: all IDs UUID strings; RS256 + JWKS; quiet hours suppress only medium/low; sensitivity ±0.10.
