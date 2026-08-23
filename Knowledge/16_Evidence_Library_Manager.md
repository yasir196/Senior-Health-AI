# 16 - Evidence Library Manager

> Permanent internal documentation. Senior Health YouTube Production System.
> This document defines how reusable evidence is stored, checked, and reused.

---

## 1. Purpose

The Evidence Library Manager keeps a reusable source and claim library for Senior Health AI projects. Its job is to reduce repeated research work while protecting the channel from stale, unsupported, or overclaimed medical statements.

The library does not replace Research_Agent or Medical_Agent. It supports them. Every project still needs a project-specific research sheet and medical gate review.

---

## 2. Library Location

All reusable evidence files live in:

`Evidence/`

Core files:

- `Evidence/README.md`
- `Evidence/evidence_sources.csv`
- `Evidence/claim_registry.csv`
- `Evidence/topic_index.md`
- `Evidence/review_queue.csv`

Optional source notes, PDFs, screenshots, or excerpts may be placed in subfolders later, but no project should depend on a local PDF alone. Every evidence entry must include a retrievable citation or source URL when available.

---

## 3. Evidence Source Record

Each source record must include:

- `source_id`
- `topic_tags`
- `condition_tags`
- `source_title`
- `authors_or_body`
- `year`
- `url`
- `evidence_tier`
- `source_type`
- `key_finding`
- `supports_claims`
- `limitations`
- `contraindications_or_cautions`
- `last_checked`
- `status`
- `used_in_projects`

Status values:

- `approved`
- `needs_review`
- `retired`
- `do_not_use`

Only `approved` sources may be reused directly in a research sheet. `needs_review` sources may guide a search but must be rechecked before use.

---

## 4. Claim Registry Record

Each claim record must include:

- `claim_id`
- `claim_text`
- `approved_wording`
- `topic_tags`
- `source_ids`
- `evidence_tier_floor`
- `claim_strength`
- `allowed_context`
- `required_caveats`
- `forbidden_wording`
- `last_medical_review`
- `status`

Claim strength values:

- `strong`
- `moderate`
- `limited`
- `preliminary`

Medical wording must match claim strength. Limited evidence requires cautious language such as "may support," "has been associated with," or "was tested in a small study." It must not become "proves," "cures," "fixes," or "guarantees."

---

## 5. Research Agent Workflow

Before searching externally, Research_Agent must:

1. Read `Evidence/topic_index.md`.
2. Search `Evidence/evidence_sources.csv` for matching topic, condition, food, medication, symptom, or body-part tags.
3. Search `Evidence/claim_registry.csv` for matching approved claims.
4. Reuse only entries marked `approved`.
5. Recheck the source if the claim is high risk, date-sensitive, guideline-based, or marked `needs_review`.
6. Add any new project-approved sources to the library only when the source is Tier 1-4 and the project medical gate passes.
7. Add unsupported or cut claims to the project research sheet, not to the approved claim registry.

Research_Agent must still create `Projects/<topic_slug>/02_research_sheet.md`.

---

## 6. Medical Agent Workflow

Medical_Agent must use the Evidence Library as a cross-check, not as an automatic pass.

For each project:

1. Compare project claims against `Evidence/claim_registry.csv`.
2. Confirm the source IDs in the claim registry still support the exact wording.
3. Check whether any required caveat from the claim registry is missing.
4. Mark stale, overused, or questionable source records in `Evidence/review_queue.csv`.
5. Do not approve a claim simply because it appears in the library.
6. Record final project approval in `13_fact_check_log.md`.

---

## 7. Add / Update / Retire Rules

Add a source when:

- It is Tier 1-4.
- It supports a reusable claim.
- It has a stable citation or official URL.
- Limitations are recorded.
- The project medical gate passed.

Update a source when:

- A guideline changes.
- A better review or trial replaces it.
- A source URL changes.
- A project finds a limitation not previously logged.

Retire or mark `do_not_use` when:

- The source is withdrawn, contradicted, obsolete, or too weak for the claim being made.
- The source only supports expert opinion or anecdote.
- The source is being used to imply a stronger claim than it supports.

---

## 8. Validation Rules

- EV1: Every approved library source must be Tier 1-4.
- EV2: Every claim must map to at least one approved source ID.
- EV3: Every claim must include approved wording and forbidden wording.
- EV4: Every claim touching medication, dosing, serious disease, reversal, or contraindications must include caveats.
- EV5: Guideline entries must have a last-checked date and review cadence.
- EV6: Library reuse cannot bypass `02_research_sheet.md` or `13_fact_check_log.md`.
- EV7: No local library entry may override `System/SYS_09_MEDICAL_RULE_ENGINE.json`.

---

## 9. Output Format

When updating the Evidence Library, use this exact summary:

```markdown
# Evidence Library Update

Date:
Project or reason:

## Sources Added
| Source ID | Title | Tier | Status |
|---|---|---:|---|

## Claims Added Or Updated
| Claim ID | Approved Wording | Source IDs | Status |
|---|---|---|---|

## Review Queue Changes
- <item or "None">

## Safety Notes
- <note or "None">
```

---

## 10. Never Do

- Never use the library as proof without checking the exact claim wording.
- Never add anecdotal sources as approved evidence.
- Never store a claim without limitations and forbidden wording.
- Never turn a limited claim into a strong claim for packaging.
- Never let performance data weaken medical rules.
- Never skip project-specific research or medical review.

---

*End of document.*
