# Content-Promise Bond Implementation Report

## Root cause
Title V2 ranked packaging/CTR strength before verifying that special hook promises were actually deliverable by the current project. There was no independent deterministic promise-evidence gate between Medical/A-B-C eligibility and winner-role assignment.

## Files/functions modified
- `v31_core.py`: Promise Inventory derivation, structural hook detection, bond evaluation, primary-promise relevance, batch classification, winner-role filtering, Markdown audit serialization, deterministic re-validation.
- `tests/test_content_promise_bond.py`: focused and multi-project regression coverage.

## Architecture
The engine reads only `01_topic_validation.md`, `02_research_sheet.md`, and `13_fact_check_log.md` once per 15-title batch, derives an immutable in-memory inventory, detects hooks from title structure, verifies the hook against current-project evidence plus primary-promise relevance, and returns PASS / FAIL / NOT_APPLICABLE. No persistent/global/disk cache is used. Existing CSV schema is intentionally unchanged; the audit is serialized into `03_titles.md` and recomputed deterministically by validation.

## Hook detection
Supported: MISTAKE, WARNING, BEFORE_ACTION, NUMBER_LIST, CAUSE_SOURCE, HABIT, MYTH, CONSEQUENCE, MULTIPLE, NONE. NUMBER_LIST also tracks its underlying category and exact requested count.

## Primary-Promise relevance
Evidence must overlap the title and be connected to tokens derived from the current project primary viewer problem / recommended angle / normalized promise / viewer desire. A special hook with no materially connected evidence fails winner eligibility.

## 15-title mucus regression
### TITLE_01
- Title: Always Feel Mucus in Your Throat After 60? Here's Where It May Really Be Coming From
- Hook: CAUSE_SOURCE
- Bond: PASS
- Reason: CAUSE_SOURCE supported by current-project evidence: For adults over 60, explain the common reasons a person may feel constant mucus, phlegm, throat clearing, or a lump-like drainage sensation in the throat, then outline medically co
### TITLE_02
- Title: Constant Mucus in Your Throat? 6 Places It May Actually Start (It's Not Always Your Throat)
- Hook: MULTIPLE
- Bond: PASS
- Reason: NUMBER_LIST 6 supported by 483 traceable current-project items
### TITLE_03
- Title: Why You Always Have Mucus in Your Throat After 60 (And What May Help Depending on the Cause)
- Hook: CAUSE_SOURCE
- Bond: PASS
- Reason: CAUSE_SOURCE supported by current-project evidence: For adults over 60, explain the common reasons a person may feel constant mucus, phlegm, throat clearing, or a lump-like drainage sensation in the throat, then outline medically co
### TITLE_04
- Title: That Constant Throat Clearing After 60: What It May Mean and What to Check First
- Hook: BEFORE_ACTION
- Bond: PASS
- Reason: BEFORE_ACTION supported by current-project evidence: For adults over 60, explain the common reasons a person may feel constant mucus, phlegm, throat clearing, or a lump-like drainage sensation in the throat, then outline medically co
### TITLE_05
- Title: Over 60 and Always Clearing Your Throat? It May Not Be Extra Mucus at All
- Hook: NONE
- Bond: NOT_APPLICABLE
- Reason: No special content-promise hook detected in title structure.
### TITLE_06
- Title: Mucus in Your Throat Every Morning After 60? The Real Source May Surprise You
- Hook: CAUSE_SOURCE
- Bond: PASS
- Reason: CAUSE_SOURCE supported by current-project evidence: For adults over 60, explain the common reasons a person may feel constant mucus, phlegm, throat clearing, or a lump-like drainage sensation in the throat, then outline medically co
### TITLE_07
- Title: Why That "Lump" or Mucus Feeling in Your Throat Won't Go Away After 60
- Hook: NONE
- Bond: NOT_APPLICABLE
- Reason: No special content-promise hook detected in title structure.
### TITLE_08
- Title: Constant Throat Mucus After 60: Nose, Stomach, or Something Else Entirely?
- Hook: CAUSE_SOURCE
- Bond: PASS
- Reason: CAUSE_SOURCE supported by current-project evidence: For adults over 60, explain the common reasons a person may feel constant mucus, phlegm, throat clearing, or a lump-like drainage sensation in the throat, then outline medically co
### TITLE_09
- Title: Always Have Phlegm in Your Throat? What May Help And When It Needs a Closer Look
- Hook: WARNING
- Bond: PASS
- Reason: WARNING supported by current-project evidence: The viewer keeps feeling mucus in the throat and does not know whether it is normal drainage, allergies, dry air, reflux, medication-related dryness, dehydration, swallowing diffic
### TITLE_10
- Title: The Everyday Habit That May Keep the Mucus-in-Throat Feeling Going After 60
- Hook: HABIT
- Bond: PASS
- Reason: HABIT supported by current-project evidence: "Constant throat clearing": habit loop plus real triggers, with a medical boundary.
### TITLE_11
- Title: Why You Keep Clearing Your Throat After 60 (And the Warning Signs Not to Ignore)
- Hook: WARNING
- Bond: PASS
- Reason: WARNING supported by current-project evidence: The phrase "how to fix it" should be repositioned before downstream packaging. A safer promise is: "why it happens, what commonly helps, and which warning signs mean it should not 
### TITLE_12
- Title: Mucus in the Throat After 60: Why It Happens and Simple Steps That May Help
- Hook: CAUSE_SOURCE
- Bond: PASS
- Reason: CAUSE_SOURCE supported by current-project evidence: For adults over 60, explain the common reasons a person may feel constant mucus, phlegm, throat clearing, or a lump-like drainage sensation in the throat, then outline medically co
### TITLE_13
- Title: If You Always Feel Mucus in Your Throat, It May Be Coming From Somewhere You'd Never Guess
- Hook: CAUSE_SOURCE
- Bond: PASS
- Reason: CAUSE_SOURCE supported by current-project evidence: For adults over 60, explain the common reasons a person may feel constant mucus, phlegm, throat clearing, or a lump-like drainage sensation in the throat, then outline medically co
### TITLE_14
- Title: Constant Throat Mucus After 60: 6 Possible Causes and What to Try First
- Hook: MULTIPLE
- Bond: PASS
- Reason: NUMBER_LIST 6 supported by 483 traceable current-project items; BEFORE_ACTION supported by current-project evidence: For adults over 60, explain the common reasons a person may feel constant mucus, phlegm, throat clearing, or a lump-like drainage sensation in the throat, then outline medically co; CAUSE_SOURCE supported by current-project evidence: For adults over 60, explain the common reasons a person may feel constant mucus, phlegm, throat clearing, or a lump-like drainage sensation in the throat, then outline medically co
### TITLE_15
- Title: Why Your Throat Always Feels Full of Mucus After 60 And When to Get It Checked
- Hook: WARNING
- Bond: PASS
- Reason: WARNING supported by current-project evidence: The phrase "how to fix it" should be repositioned before downstream packaging. A safer promise is: "why it happens, what commonly helps, and which warning signs mean it should not 

## Winner eligibility before/after
Before: score-first role assignment could select a special-promise title without an independent content-delivery gate. After: `content_promise_bond == FAIL` remains visible/auditable but is excluded from WINNER, SAFE_ALTERNATIVE, and HIGH_UPSIDE_EXPERIMENT selection. Candidate text is never rewritten or deleted.

## Deterministic validator
Validator recomputes Content-Promise results from current-project sources, verifies the 15-row Markdown audit, and rejects protected recommendation roles with bond FAIL. Model-authored PASS cannot override this recomputation.

## Candidate immutability
PASS in focused regression: candidate title bytes remain unchanged by Content-Promise evaluation.

## Source-read/call counts
- Promise Inventory source reads per 15-title batch: 3.
- Inventory is reused across all 15 evaluations.

## Tests
- Focused Title/Content-Promise suite: 103 passed.
- Full suite: 532 passed, 1 failed. The single failure is `tests/test_anchor_project_vocab_runtime.py::test_current_project_builds_subject_and_payoff_from_its_own_sources` (existing A/B/C gate expectation for standalone `comfort` token); Content-Promise code does not modify frozen A/B/C functions.

## Frozen-scope confirmation
- P1/P2 unchanged.
- P3 unchanged.
- Medical Gate semantics unchanged.
- Frozen A/B/C implementation unchanged.
- >=8 anchor requirement unchanged.
- Opus Writer and candidate generation unchanged.
- No Thumbnail, Script, Production, SEO, Evidence Overlay, CapCut, B-roll, or image-generation code changed.
