# 07 — Component demo on Wed 11 Nov 2026 (priority until then)

> **Added 7 Nov 2026.** The individual component demos are on **Wed 11 Nov 2026**, earlier than the week of
> 7 Dec assumed in `06_ROADMAP_AND_DEMO.md`. This file only sets **priority and dates until the demo**. The
> project plan itself (`06` §1–§6, the component plans, their task lists, `02_CONTRACTS.md` and `AGENTS.md`)
> is unchanged: after the demo, continue it as written, including every task moved out of the way here.
> Where this file and another doc disagree **about dates or order before 11 Nov**, this file wins; for
> everything else the other docs win.

## For AI coding assistants
If you are an assistant working in this repo before 11 Nov 2026: read this file after `AGENTS.md`. Do first
the tasks your component's live-demo script (`docs/components/Cx_*.md` §10.1) needs, in the order of §2
below. Stubs from your plan's §1.1 are fine for the demo. All rules in `AGENTS.md` §3 still apply.

## 1. Checkpoints to the demo
| Checkpoint | Date | Exit criteria |
|---|---|---|
| **D0 Foundation** (= M0) | Sun 8 Nov | M0's criteria (`06` §1) |
| **D1 Demo features** | Mon 9 Nov, end of day | Every step of your plan's §10.1 live-demo script works on the local stack (stubs allowed, §3); backend merged on `main` |
| **D2 Deployed** | Mon 9 Nov, night | Stack runs on EC2 with real S3, SNS and Secrets Manager (`03` §8, see §5); upload → classify → alert works if C1 and C3 are in |
| **D3 Code freeze** | Tue 10 Nov, 6 pm (proposed) | Only demo-blocking fixes after this; demo runs from a tagged commit |
| **D4 Component demos** | **Wed 11 Nov** | Live demos (+ scenario videos if the course asks for them that day) |

**To confirm with the instructor:** (1) must the demo run on AWS EC2, or is the local Docker stack accepted;
(2) is the scenario video (`06` §4.2) due on 11 Nov too; (3) is the rubric in `06` §4 the one used. Until
confirmed, prepare for EC2 + video.

## 2. Day by day (proposed; each owner checks and corrects their column)
| Day | Whole team | Ekant (C1) | Prathamesh (C2) | Renuka (C3) | Mohit (C4) |
|---|---|---|---|---|---|
| **Sat 7 Nov** | Confirm §1 questions; 30-min call: each owner picks the tasks their §10.1 script needs | C1-01, C1-02 (0001 grants `c1.houses, c1.rooms` to `c2_reader`, C1 plan §2.1), start C1-03 | Rehearse the C2 script locally; demo setup script; fix findings | PR #8 review (C3-10); start C3-15/C3-17 UI | Make targets `up/down/seed/token` (`03` §6); C4-12 Settings UI (C2's and C4's scripts both use it) |
| **Sun 8 Nov** | **AWS setup evening** (C4-16, `03` §8), everyone helps; D0 check | C1-03, C1-04, C1-06, C1-10 seed rows (IDs from `scripts/seed_ids.py`) | Real SNS on AWS, subscribe + confirm demo emails, smoke test | C3-15, C3-16, C3-17 | C4-16 lead; C4-08, C4-13 |
| **Mon 9 Nov** | Backend merged (D1); deploy to EC2 (D2); integration I-1/I-2 | C1-07, C1-11 … C1-13 | C2-11 if C1-07 is in; C2-16 if C1 + C3 `HANDOFF_MODE=call` are in; script on EC2 | C3-18; `HANDOFF_MODE=call`; deploy | C4-14; deploy |
| **Tue 10 Nov** | Code freeze (D3); rehearse each script twice on EC2; videos if due; `06` §4.3 checklist | Fixes, rehearsal | Fixes, rehearsal, reset demo data, confirm SNS | Pre-build C3 image on EC2, warm model, rehearsal | Fixes, rehearsal |

## 3. Priority rules until the demo
- **Your plan's §10.1 live-demo script decides the order.** Do the tasks its steps need first; other tasks
  move to after the demo (they stay in the plan). Say in your PR what your demo still stubs.
- **Stubs from each plan's §1.1 are fine for the demo** (`c2_fake_detection.py`, `c3_enqueue.py`, seed rows,
  `NOTIFIER=log` as fallback). Every demo must still work with only C4 login if a teammate's part is late.
- **Can wait until after the demo:** Playwright specs (rehearse by hand), the final-project items (`06` §6),
  background jobs your script does not show, UI polish.
- **Nothing else changes:** contracts stay frozen, lanes and tenant isolation as in `AGENTS.md` §3, tests for
  what you demo (the rubric runs `make test-cx`), CI green on `main`. Review PRs within a few hours.
- **If AWS time runs short**, Postgres may run as a container on the EC2 host for the demo (same
  `infra/db/init.sql`) instead of RDS; S3, SNS and Secrets Manager stay real. RDS (`03` §8) remains the plan.
  Decision: Mohit (AWS lead).

## 4. Status on 7 Nov (what is on `main`)
| Component | Done | Needed for its demo script |
|---|---|---|
| C1 | — (no service yet) | C1-01 … C1-07, C1-10 … C1-13 (C1-05 and C1-08 appear in the C1 script) |
| C2 | C2-01 … C2-10, C2-12 … C2-15 | C2-17's real SNS on EC2; C2-11 and C2-16 when C1/C3 allow |
| C3 | C3-01 … C3-09; C3-10 in PR #8 (changes requested) | C3-15 … C3-18 UI, C3-19 EC2; C3-11 … C3-13 as far as the C3 script shows them |
| C4 | C4-01 … C4-07, C4-10, C4-11, C4-15 | C4-12, C4-08/C4-13, C4-14, C4-16 |
| Platform | compose, init.sql, Caddy, CI, `make seed-c4`, `make seed-c2` | `make up/down/seed/token/reset-demo` (`03` §6), `HANDOFF_MODE=call` for `c3-worker` |

Dependencies to watch: C2 answers 503 on evaluate until `c1.houses`/`c1.rooms` exist with the `c2_reader`
grant (C1 plan §2.1), so those come first in C1.

## 5. AWS notes for the demo (`03` §8 steps unchanged)
- `03` §8 says "week 3"; for the 11 Nov demo the AWS setup is due **Sun 8 Nov**.
- **IAM policy, step 5:** besides the SNS actions listed there, add `sns:Unsubscribe` and
  `sns:GetSubscriptionAttributes` on `arn:aws:sns:<region>:<acct>:homeai-*`, and `sns:ListTopics` on `*`.
  C2-09/C2-10 (subscription sync, retries) already call them; without them C2 gets access denied on AWS.
  For Mohit's review; `03` §8 can be updated after the demo.
- Keep `DEMO_MODE=1` and `NOTIFIER=sns` in the EC2 `.env` for the demos (demo fallbacks such as
  `c2_fake_detection.py` and C2's `view_link` need DEMO_MODE).
- Confirm the SNS email subscriptions of the demo contacts by Sun 8 Nov and re-check on Tue 10 Nov.
