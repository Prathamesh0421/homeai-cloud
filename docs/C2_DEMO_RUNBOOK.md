# C2 demo runbook — Alert Tracking and Monitor (Prathamesh)

The script is the C2 plan §10; this page is how to run it on the EC2 demo host, step by step.
Rubric (06 §4): every C2 function through the UI, backend proof, edge cases, unit tests, on EC2.

**URL** http://44.226.166.194 · **Swagger** http://44.226.166.194/api/v1/docs/c2
**Logins** (password `Demo!2026`): `ops@homeai.test` (cloud staff: Alert Rules) ·
`owner.maple@acme.test` (Maple St owner: Alerts) · `owner.oak@acme.test` (isolation check).
**Contacts** (Maple, priority order): Alice `…+alice@gmail.com` (family) → Bob `…+bob` (caregiver)
→ Carol `…+carol` (neighbor); all three land in one Gmail inbox.

Commands marked **EC2** run on the host from the laptop, e.g.
`ssh homeai-ec2 'cd ~/homeai-cloud && make demo-c2-detect ARGS="--label glass_break --conf 0.78"'`.
Steps marked **⏳ C1** need C1's `houses`/`rooms` tables on RDS (C2 answers 503 without them).

## 1. Before (day before, then 1 hour before)
| | Step | How |
|---|---|---|
| ☐ | Instance running, all 6 containers up | Console → EC2 → Start; then **EC2** `docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml --profile gateway --profile c3 up -d` (no restart policy) |
| ☐ | C2 healthy | `curl http://44.226.166.194/api/v1/health/c2` → `"status":"ok"` |
| ☐ | SNS subscriptions confirmed | SNS console, topic `homeai-house-22222222-0000-0000-0000-0000000000a1`: 3 × confirmed |
| ☐ | Clean alerts | **EC2** `make demo-c2-reset ARGS=--yes` |
| ☐ | Quiet hours back to normal | **EC2** `make demo-c2-quiet-hours ARGS="--set 22:00-07:00"` (step 5 changes them) |
| ☐ | Tests run green | laptop `make test-c2-full` (482 passed, 99%) |
| ☐ | Tabs open | 1 ops → Alert Rules · 2 Maple owner → Alerts · 3 Swagger · 4 SNS console · 5 terminal |
| ☐ | Phone | Gmail open, notifications on; browser zoom 110% on the laptop |
| ☐ | Rehearsed twice | this page, top to bottom |

## 2. Live demo (~8 min; timings from 06 §4.1)
**0:00–0:30 · Where C2 sits.** Detections from C3 → rule engine → alert once → emails to contacts
in priority order (SNS) with a signed 24 h link → lifecycle with audit trail. C2 owns schema `c2`
and the SNS topics; it only *reads* C4 settings/contacts, C1 houses/rooms, C3 detections.

**0:30–2:00 · Alert Rules (tab 1, `ops@homeai.test`).**
1. Show the tenant defaults (7 per tenant): severity, min confidence, enabled, false positives (30 d).
2. ⏳ C1 · **New rule** → One house = Maple `22222222-0000-0000-0000-0000000000a1`, type *Possible
   fall*, room Bathroom `33333333-0000-0000-0000-00000000a104`, min confidence `0.70` → created.
3. **Duplicate**: the same rule again → toast `409 duplicate_rule`. (No C1 needed: **New rule** →
   Tenant default, Acme Care, *Glass break* → 409, the default already exists.)
4. **Invalid**: min confidence `1.5`, or no label ticked → the error shows at the field (checked in
   the browser, and again by the API). The API's own 422: Swagger `POST /alert-rules` with
   `"trigger_labels": ["banana"]` → `422` with `details: [{field, issue}]`.
5. **Disable** a rule → confirm dialog → Off; **Enable** it again.

**2:00–4:30 · An alert end to end.** ⏳ C1
1. Trigger. Real path: in C1 (log in as `iot@acme.test`) upload `glass_break.wav` to a Maple feed
   in Feed Detail → C3 classifies it → C2 raises the alert. Fallback that still plays a real clip:
   copy that clip's media id from C1's Clip Library, then
   **EC2** `make demo-c2-detect ARGS="--label glass_break --conf 0.78 --media-id <clip id>"` →
   `C2 answered 201 … "decision": "alert"`; note the printed `--resend <detection_id>`.
   (Without `--media-id` the alert works but shows "The recording is not available".)
2. Tab 2 (Maple owner) → **Alerts**: the alert appears within 15 s (polling) — *Glass break*, high,
   Entryway, open.
3. Phone: 3 emails, Alice → Bob → Carol (subject `[HomeAI] HIGH Glass break - Maple St`). Open one
   → **Alert View**, no login: type, severity, room, what was heard, "call 911". No owner PII.
4. **Alert Detail**: **Play recording** (C1 clip, C2-11), labels with the threshold, timeline,
   contacts (sent / pending), demo link. The phone's Alert View plays the same clip.
   *Resolve* is disabled while open → **Acknowledge** with a note → **Resolve**. The phone's Alert
   View updates within 30 s.
5. Swagger (tab 3): `POST /alerts/{id}/resolve` on an *open* alert → `409 invalid_state {from, to}`.

**4:30–5:45 · Rules and edge cases.**
| Show | Command (**EC2**) | Expected |
|---|---|---|
| Quiet hours hold low alerts | `make demo-c2-quiet-hours ARGS=--cover-now`, then `make demo-c2-detect ARGS="--label cough --conf 0.80"` | `no_alert`, reason `quiet_hours`; nothing in Alerts |
| …but not high ones | `make demo-c2-detect ARGS="--label glass_break --conf 0.80"` | `alert` (high bypasses quiet hours), emails sent |
| Below threshold | `make demo-c2-detect ARGS="--label glass_break --conf 0.40"` | `no_alert`, `below_threshold` (0.55) |
| Room rule wins (⏳ C1, after step 2.2) | `make demo-c2-detect ARGS="--label fall_indicator --conf 0.68 --room Bathroom"` | `no_alert`, `below_threshold` (room rule 0.70, not the default 0.65) |
| Idempotency | `make demo-c2-detect ARGS="--resend <detection_id>"` | `duplicate: true`, same `alert_id`, no new email |
| Expired link | `make demo-c2-expired-link` → open the printed link | "This link has expired" (API `401 token_expired`); change one character → "not valid" (404) |
| Isolation | log in as `owner.oak@acme.test` → Alerts | Maple's alerts are not there |

**5:45–6:45 · Backend proof.** Swagger `/api/v1/docs/c2` (evaluate, lifecycle, rules, alert-view);
SNS console → the Maple topic → 3 confirmed subscriptions, each with its `contact_id` filter policy;
logs: **EC2** `docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml logs --tail 30 c2-alerts`
(the `subscription sync` and `evaluate` lines).

**6:45–7:30 · Tests and deployment.** Laptop `make test-c2-full` → 482 passed, coverage 99%;
**EC2** `docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml --profile gateway --profile c3 ps`.

**After.** **EC2** `make demo-c2-quiet-hours ARGS="--set 22:00-07:00"` and `make demo-c2-reset ARGS=--yes`.

## 3. If something goes wrong
| Problem | Do |
|---|---|
| "The recording is not available" | The alert's `media_id` is not a C1 clip (fake detection without `--media-id`), or C1 is down |
| Evaluate answers 503 `c1` | C1's tables are missing on RDS: show the rule engine with the local stack instead (`docs/03` §4), or the decision tables in the unit tests |
| Email slow / in spam | Show the alert's contacts (sent) in Alert Detail and open the link from there (DEMO_MODE `view_link`) |
| Site down | Console → instance running? Then the `up -d` command from §1 |
| `make demo-c2-detect` refused | `ENV=prod` needs `DEMO_MODE=1` in the host's `.env` |

## 4. Scenario video (~5 min, C2 plan §10.2 "Night-time break-in at Maple St")
Title card (10 s) → quiet hours on (`--cover-now`) → glass break during quiet hours → high alert
bypasses them → 3 emails in order on the phone → neighbor (Carol) opens the signed link → owner
acknowledges, checks the evidence, resolves with a note → a cough during quiet hours is held (no
alert) → ops tunes the rule after a false positive (*Mark false positive* in Alert Detail, then the
rule's false-positive count in Alert Rules). Show the EC2 URL in the address bar once and one
backend view (Swagger or SNS). Record twice, keep the better take; ≤ 7 min, MP4.
