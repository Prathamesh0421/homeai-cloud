# HomeAI Cloud — Deliverable #2 Component Design (Overleaf project)

CMPE 281, Fall 2026, Instructor Jerry Gao. Project Option #1. Built on the HomeAI Cloud SRS v3.

## What to submit
**One group PDF:** compile `main-Group.tex` (Menu -> Main document -> main-Group.tex -> Recompile).
It contains a group title page, a table of contents, then one Part per member:

| Member | Name | Component | Part | Single-member file |
|---|---|---|---|---|
| 1 | Ekant Kapgate | C1 Home-Based IoT Device Manager | I | `main-C1.tex` |
| 2 | Prathamesh Ravindra Sawant | C2 Alert Tracking and Monitor | II | `main-C2.tex` |
| 3 | Renuka Prasad Patwari | C3 System Database Management | III | `main-C3.tex` |
| 4 | Mohit Manoj Barade | C4 System Dashboard | IV | `main-C4.tex` |

Compiler: pdfLaTeX (Overleaf default).

## Layout
- `preamble.tex` shared preamble (title page, `\figH` pinned figures, tables, code, pdflscape)
- `main-Group.tex` the group submission; `main-C1..C4.tex` single-component builds
- `sections/Cx/body.tex` the five D2 sections for each component
- `sections/references.tex` shared references ("Software Component Design" search, UML, OpenAPI, RFCs, AWS)
- `figures/Cx/*.png` diagrams per component

## Each component contains (D2 rubric)
1. Overview: purpose, objectives, scope + assumptions, actors/usage, function partition, FR mapping,
   **function specification table** (inputs, outputs, pre/post-conditions)
2. Application interface design and analysis: conventions, **API catalogue**, parameter tables and
   examples, **error model**, **connectivity APIs**, API design analysis
3. Function / data / DB design and behavior: **class diagram + class specification**, **ER diagram +
   data dictionary + indexes**, function table, flowchart, pseudocode, **state diagram**,
   **two or more sequence diagrams**
4. Business logic: decision tables
5. GUI: style guide, storyboard, function partition tree, **marked-up wireframe + legend**, templates

## Platform-wide decisions (consistent across C1–C4)
- All IDs are UUID strings (incl. `media_id`, `detection_id`); responses use `{data, meta}` / `{error}`.
- C4 signs user JWTs (RS256, 60 min) and 15-min service tokens; others verify via C4's JWKS.
- C1 writes clips `queued`; C3 claims (max 3 attempts), classifies, and calls C2 `/alerts/evaluate`
  with `{detection_id, media_id, house_id, room_id, top_label, top_confidence, labels, detected_at}`.
- C2 is idempotent on `detection_id`; house sensitivity (C4) shifts rule thresholds ±0.10;
  critical and high alerts bypass quiet hours; clip playback links come from C1.
- Resolved TBDs: TBD-1 label map (C3), TBD-2 default thresholds (C2), TBD-4 24 h signed link (C2).
  TBD-3 / TBD-5 (measured latency, scaling) remain for Deliverable #3.
