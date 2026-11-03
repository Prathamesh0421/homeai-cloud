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

## Changes
- 2026-11-03 — C2 — Added `GET /alert-rules/{id}` (cloud_staff) so the `Location` header of `POST /alert-rules` resolves; rule responses carry `ETag: "<version>"` for `If-Match`. `POST /alert-rules/defaults` takes `{tenant_id}` in the body (as in the API table). — agreed by Prathamesh (C2 owner)
- 2026-11-03 — C2 — Rule selection (C2 plan §4.1 step 4): per alert type the most specific applicable rule wins for the detection's room (room rule > whole-house rule > tenant default). A room-only house rule replaces the default only in its room; a disabled house rule does not hide the default. — agreed by Prathamesh (C2 owner)
- 2026-11-03 — C2 — RuleEngine (C2 plan §4.1 step 6): the label is checked before the service, so `service_disabled` is only reported when a rule for the detected label exists but its service is off (previously any disabled service turned every unmatched detection into `service_disabled`). Thresholds are rounded to 2 decimals after the sensitivity shift (avoids 0.55+0.10 float drift). — agreed by Prathamesh (C2 owner)
