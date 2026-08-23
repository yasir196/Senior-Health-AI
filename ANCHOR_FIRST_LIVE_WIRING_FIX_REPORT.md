# Anchor-First Live Wiring Fix Report

## Problem fixed

The code already contained Phase 1-3 helper logic, but the live UI/orchestrator still created projects with only `topic` and did not persist an authoritative anchor at project creation. The Claim Map therefore was not guaranteed to exist before Topic Validation, and later Title runs still depended on manually re-entering the runtime anchor.

## Changes

1. New Project is now **Anchor / Outlier Title** first.
2. `project.json` persists both `topic` (backward compatibility) and a separate authoritative `anchor_title`.
3. Project creation immediately writes `01a_anchor_claim_map.json` using the exact supplied anchor.
4. `resolve_title_anchor()` now resolves, in order: explicit orchestrator anchor, then persisted `project.json.anchor_title`. It still never reconstructs an anchor from topic, slug, research, generated titles, or old title artifacts.
5. Topic Validation command explicitly consumes `01a_anchor_claim_map.json` as a packaging hypothesis and must not rewrite/approve the claim.
6. Research + Medical Gate 1 command explicitly consumes Claim Map + Topic Validation, neutrally tests/falsifies the exact hypothesis, and requires `13a_title_repair_blueprint.json` for anchor-first projects.
7. Workflow UI now shows an **Anchor-First Preflight** with the authoritative anchor and Claim Map READY/MISSING status.
8. Titles automatically inherit the persisted anchor when no explicit override is entered, enabling the existing Minimum Necessary Transformation Phase-3 contract without manual anchor re-entry.

## Neuropathy smoke check

Input:
`5 Simple Exercises That Relieve Neuropathy in Feet & Legs After 60`

Claim Map correctly extracts:
- hook_number: `5`
- hook_packaging: `5 Simple Exercises`
- hypothesis_claim: `Relieve Neuropathy`
- anatomy_target: `Feet & Legs`
- audience_filter: `After 60`
- sentence_skeleton: `5 Simple Exercises That [HYPOTHESIS_CLAIM] in [ANATOMY_TARGET] [AUDIENCE]`

## Protected scope

No Title V2 CSV schema, A/B/C classifier, >=8 threshold, Content-Promise Bond, scoring, Thumbnail, Script, Production, SEO, or CapCut behavior was intentionally changed.

## Tests

Focused Anchor-First + runtime-anchor tests: **21 passed**.
Full suite: **537 passed, 8 failed**. Of the 8 failures, 1 is the already-documented unrelated frozen A/B/C `comfort` vocabulary expectation; 7 are fixture-dependent production/image tests whose referenced project fixture files are absent from this supplied ZIP. No new failure was observed in the focused Anchor-First/runtime-anchor tests.
