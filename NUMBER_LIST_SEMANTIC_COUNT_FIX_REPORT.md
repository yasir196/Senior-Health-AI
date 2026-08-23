# NUMBER_LIST Semantic Count Fix Report

## Scope
Correctness-only fix to Content-Promise Bond NUMBER_LIST verification. No candidate generation, wording, scoring, ranking, Medical Gate, Frozen A/B/C, anchor semantics, >=8 rule, CSV schema, or downstream system was intentionally modified.

## Root Cause
The previous implementation built NUMBERABLE_ITEMS by splitting cause/source evidence sentences into raw fragments and used len(items). Evidence volume therefore became numeric-promise quantity, allowing repeated/source-table fragments to inflate counts (e.g. 483 traceable items).

## Modified Files
- `v31_core.py`: NUMBER_LIST semantic inventory/counting helpers, numeric-promise extraction, category resolution, semantic deduplication.
- `tests/test_content_promise_bond.py`: focused semantic-count, repetition, exercise, warning, four-project isolation, and unresolved-category regressions.

## New Algorithm
1. Read the same three authorized current-project files once per batch.
2. Derive a reusable semantic inventory from approved/summary promise sections.
3. Extract explicit numeric promise N without confusing age cues such as `Over 60` / `After 60`.
4. Resolve the promised noun to a generic semantic role (CAUSE, SOURCE_ORIGIN, WARNING_SIGN, EXERCISE, FOOD, MISTAKE, HABIT, METHOD_ACTION, etc.).
5. Extract category-list concepts from current-project evidence.
6. Normalize and semantically deduplicate exact repeats and surface-near paraphrases.
7. PASS only when distinct_supported >= required. Unresolved categories deterministically FAIL with `NUMBER_LIST_UNRESOLVED_CATEGORY`.
8. Multi-hook evaluation remains conjunctive: a failed NUMBER_LIST returns overall FAIL even when another material hook could pass.

## Mucus Regression Numeric Diagnostics
Specified Rank 1 title (`6 Places`): `NUMBER_LIST: required=6; category=SOURCE_ORIGIN; distinct_supported=14; result=PASS`.

Specified Rank 11 title (`6 Possible Causes`): `NUMBER_LIST: required=6; category=CAUSE; distinct_supported=14; result=PASS`.

These counts are semantic inventory concepts, not raw evidence fragments. Diagnostics include a bounded concept-label sample for auditability.

## Tests
Focused Content-Promise tests: 14 passed.

Full suite: 538 passed, 1 failed. The remaining failure is the pre-existing unrelated Frozen A/B/C runtime-vocabulary test expecting standalone `comfort` in Gate C. It was not modified under this task.

## Source Reads
`source_reads = 3`: one read of each authorized project source per batch; inventory reused across all 15 titles.

## Leakage Review
Modified production Content-Promise code contains no mucus/throat/reflux/beetroot fixture vocabulary. Existing unrelated occurrences elsewhere in `v31_core.py` were not introduced or changed by this fix.
