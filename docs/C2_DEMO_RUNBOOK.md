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
C1 is deployed on EC2 (11 Nov), so every step below runs there; the full path (upload in C1 → C3 →
C2 → 3 emails → Alert View on the phone with the clip) was run end to end on 11 Nov.

**Nobody redeploys during rehearsal or the demo.** A rebuild of `c2-alerts` while C3 hands a
detection over leaves that detection `pending` (no alert, no automatic resend): this happened on
11 Nov. Agree a quiet window with the team.

## 1. Before (day before, then 1 hour before)
| | Step | How |
|---|---|---|
| ☐ | Instance running, all 7 containers up (c1-iot, c2-alerts, c3-data, c3-worker, c4-dashboard, caddy, mongo) | Console → EC2 → Start; then **EC2** `docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml --profile gateway --profile c3 --profile c1 up -d` (no restart policy) |
| ☐ | C2 healthy | `curl http://44.226.166.194/api/v1/health/c2` → `"status":"ok"` |
| ☐ | SNS subscriptions confirmed | SNS console, topic `homeai-house-22222222-0000-0000-0000-0000000000a1`: 3 × confirmed |
| ☐ | (Only for the optional live-topic step, §2 5:45) Oak has no contacts and no topic | Services & settings → Oak Ave: no contacts; SNS: no `homeai-house-…0000000000a2`. C2 never deletes topics: after rehearsing the step, delete that topic in the SNS console (its subscriptions go with it) |
| ☐ | Clean alerts | **EC2** `make demo-c2-reset ARGS=--yes` |
| ☐ | Quiet hours back to normal | **EC2** `make demo-c2-quiet-hours ARGS="--set 22:00-07:00"` (step 5 changes them) |
| ☐ | Tests run green | laptop `make test-c2-full` (499 passed, 99.96%, ~20 s) |
| ☐ | Tabs open | 1 ops → Alert Rules · 2 Maple owner → Alerts · 3 Swagger · 4 SNS console · 5 terminal |
| ☐ | Phone | Gmail open, notifications on; browser zoom 110% on the laptop |
| ☐ | Rehearsed twice | this page, top to bottom |

## 2. Live demo (~8 min; timings from 06 §4.1)
**0:00–0:30 · Where C2 sits.** Detections from C3 → rule engine → alert once → emails to contacts
in priority order (SNS) with a signed 24 h link → lifecycle with audit trail. C2 owns schema `c2`
and the SNS topics; it only *reads* C4 settings/contacts, C1 houses/rooms, C3 detections.

**0:30–2:00 · Alert Rules (tab 1, `ops@homeai.test`).**
1. Show the tenant defaults (7 per tenant): severity, min confidence, enabled, false positives (30 d).
2. **New rule** → One house = Maple `22222222-0000-0000-0000-0000000000a1`, type *Possible
   fall*, room Bathroom `33333333-0000-0000-0000-00000000a104`, min confidence `0.70` → created.
3. **Duplicate**: the same rule again → toast `409 duplicate_rule`. (No C1 needed: **New rule** →
   Tenant default, Acme Care, *Glass break* → 409, the default already exists.)
4. **Invalid**: min confidence `1.5`, or no label ticked → the error shows at the field (checked in
   the browser, and again by the API). The API's own 422: Swagger `POST /alert-rules` with
   `"trigger_labels": ["banana"]` → `422` with `details: [{field, issue}]`.
5. **Disable** a rule → confirm dialog → Off; **Enable** it again.

**2:00–4:30 · An alert end to end.**
1. Trigger. Real path: in C1 (log in as `iot@acme.test`) → Feeds → **Maple St · Kitchen Mic**
   (`66666666-…-00000000a101`, audio, enabled) → upload `demo_clips/glass_break.wav` → C3 classifies
   it → C2 raises the alert, ~1.5 s after the upload. Every house has a "Kitchen Mic": check the house
   column (an upload to Oak's raises an Oak alert with no emails, as Oak has no contacts).
   `glass_break.wav` scores **0.557** against Maple's threshold **0.55** (medium sensitivity): it
   passes every time (same file, same model), but only just; if C3's model changes, re-check it.
   Fallback when C3 is down: the clip stays unclassified, so copy its media id from C1's Clip
   Library, then **EC2** `make demo-c2-detect ARGS="--label glass_break --conf 0.78 --media-id <clip id>"` →
   `C2 answered 201 … "decision": "alert"`; note the printed `--resend <detection_id>`.
   `--media-id` only works for a clip C3 has **not** classified (C3 keeps one detection per clip:
   index `ux_media_id`; a classified clip gives `DuplicateKeyError`). Without `--media-id` the alert
   works but shows "The recording is not available".
2. Tab 2 (Maple owner) → **Alerts**: the alert appears within 15 s (polling) — *Glass break*, high,
   **Kitchen**, open. Clicking the row opens the side panel (recording, what was heard, timeline,
   actions); click the **alert name** to open the full Alert Detail page.
3. Phone: 3 emails, Alice → Bob → Carol (subject `[HomeAI] HIGH Glass break - Maple St`). Open one
   → **Alert View**, no login: type, severity, room, what was heard, "call 911", **Play recording**
   (C2 fetches the clip URL from C1 with its own service token). No owner PII.
4. **Alert Detail** (via the alert name): **Play recording** (C1 clip, C2-11, the owner's login),
   labels with the threshold, timeline, **Contacts notified** (only on this page, not in the side
   panel: in-app + Alice/Bob/Carol sent, each with a demo link). *Resolve* is disabled while open →
   type a note, then **Acknowledge** → type a note, then **Resolve** (notes are optional: type them
   before clicking, or the timeline shows none). The phone's Alert View updates within 30 s.
5. Swagger (tab 3): `POST /alerts/{id}/resolve` on an *open* alert → `409 invalid_state {from, to}`.
   Raise one first if none is open (the quiet-hours glass break below leaves one open).

**4:30–5:45 · Rules and edge cases.** All rows except "room rule wins" were run on EC2 on 11 Nov
with the results shown. The glass break in quiet hours sends 3 more emails.
The two quiet-hours rows use **real uploads** (Maple St · Kitchen Mic), so the alert has a recording.
A `make demo-c2-detect` detection without `--media-id` gets a made-up clip id, and its emails open
an Alert View with "The recording is not available". Use the script for the rows that need no
recording, and as the fallback for the quiet-hours rows if C3 is down (same command with `--label`).
| Show | Command (**EC2**) / action | Expected |
|---|---|---|
| Quiet hours hold low alerts | `make demo-c2-quiet-hours ARGS=--cover-now`, then upload `cough.wav` (fallback `make demo-c2-detect ARGS="--label cough --conf 0.80"`) | `no_alert`, reason `quiet_hours` (C2 log `evaluate decision`); nothing in Alerts. Check in the first rehearsal that C3 labels `cough.wav` as `cough` at ≥ 0.55; script result checked 11 Nov |
| …but not high ones | upload `glass_break.wav` (fallback `make demo-c2-detect ARGS="--label glass_break --conf 0.80"`) | `alert` (high bypasses quiet hours), emails sent, recording plays |
| Below threshold | `make demo-c2-detect ARGS="--label glass_break --conf 0.40"` | `no_alert`, `below_threshold` (0.55) |
| Room rule wins (after step 2.2) | `make demo-c2-detect ARGS="--label fall_indicator --conf 0.68 --room Bathroom"` | `no_alert`, `below_threshold` (room rule 0.70, not the default 0.65) |
| Idempotency | `make demo-c2-detect ARGS="--resend <detection_id>"` | `duplicate: true`, same `alert_id`, no new email |
| Expired link | `make demo-c2-expired-link` → open the printed link | "This link has expired" (API `401 token_expired`); change one character → "not valid" (404) |
| Isolation | log in as `owner.oak@acme.test` → Alerts | Maple's alerts are not there |

**5:45–6:45 · Backend proof.** Swagger `/api/v1/docs/c2` (evaluate, lifecycle, rules, alert-view);
SNS console → the Maple topic → 3 confirmed subscriptions, each with its `contact_id` filter policy;
logs: **EC2** `docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml logs --tail 30 c2-alerts`
(the `subscription sync` and `evaluate` lines).

*Optional (~1–2 min, if time allows): a topic and subscription created live.* C2 makes one SNS topic
per house (`homeai-house-<house_id>`) and one email subscription per C4 emergency contact (filter
policy on `contact_id`), on the 5-min sync job, on **Sync email subscriptions**, or when an alert
fires. Use **Oak Ave**: it has no contacts, so no topic yet, and Maple's 3 subscriptions stay as
they are. Use an address whose inbox is open on a phone (a second address of your own is easiest;
a teammate's works if they click the AWS link when asked and expect Oak's alert emails afterwards).
1. `ops@homeai.test` → **Services & settings** → house **Oak Ave** → add an emergency contact
   (e.g. "Dave Oak", type *neighbor*, that address).
2. **Alert rules** → **Sync email subscriptions** → toast + summary "… 1 waiting for email
   confirmation".
3. SNS console → Topics → new **`homeai-house-22222222-0000-0000-0000-0000000000a2`** → the
   subscription is *Pending confirmation*, filter policy `{"contact_id": ["…"]}`.
4. Phone: open "AWS Notification – Subscription Confirmation" → **Confirm subscription**.
5. **Sync email subscriptions** again → 0 waiting; the subscription has a real ARN in SNS.
6. (Optional) upload `glass_break.wav` to **Oak**'s Kitchen Mic → only that address is emailed
   (Oak's sensitivity is `high`: glass-break threshold 0.45).

Afterwards, if the address is not yours: delete the contact in Services & settings → **Sync email
subscriptions** → "1 removed". Confirm first: AWS does not let C2 remove a *pending* subscription
(it expires by itself after 3 days). An "unsubscribe" click in any SNS email also removes it; the next
sync then creates a new one that needs confirming again. Do not re-run the C4 seed after this.

**6:45–7:30 · Tests and deployment.** Laptop `make test-c2-full` → 499 passed, coverage 99.96%;
**EC2** `docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml --profile gateway --profile c3 --profile c1 ps`.

**After.** **EC2** `make demo-c2-quiet-hours ARGS="--set 22:00-07:00"` and `make demo-c2-reset ARGS=--yes`.

## 3. If something goes wrong
| Problem | Do |
|---|---|
| "The recording is not available" | The alert's `media_id` is not a C1 clip (fake detection without `--media-id`), or C1 is down |
| Upload done but no alert | **EC2** `docker compose … logs --since 5m c3-worker c2-alerts`: `handoff failed; marking pending` = C2 was down at that moment (redeploy): upload again. `below_threshold` = the clip scored too low |
| `make demo-c2-detect --media-id` → `DuplicateKeyError` | That clip already has C3's detection: use a clip C3 has not classified, or drop `--media-id` |
| Evaluate answers 503 `c1` | C1 is down or its tables are missing: show the rule engine with the local stack instead (`docs/03` §4), or the decision tables in the unit tests |
| Email slow / in spam | Show the alert's contacts (sent) in Alert Detail and open the link from there (DEMO_MODE `view_link`) |
| Site down | Console → instance running? Then the `up -d` command from §1 |
| `make demo-c2-detect` refused | `ENV=prod` needs `DEMO_MODE=1` in the host's `.env` |

## 4. Scenario video (~5 min, C2 plan §10.2 "Night-time break-in at Maple St")
Title card (10 s) → quiet hours on (`--cover-now`) → upload `glass_break.wav` to Maple Kitchen Mic
during quiet hours (a real upload, so the neighbor's view can play the clip) → high alert
bypasses them → 3 emails in order on the phone → neighbor (Carol) opens the signed link → owner
acknowledges, checks the evidence, resolves with a note → a cough during quiet hours is held (upload
`cough.wav`; no alert) → ops tunes the rule after a false positive (*Mark false positive* in Alert Detail, then the
rule's false-positive count in Alert Rules). Show the EC2 URL in the address bar once and one
backend view (Swagger or SNS). Record twice, keep the better take; ≤ 7 min, MP4.
