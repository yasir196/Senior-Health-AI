# Anchor-First Phase 3 Implementation Report

## Objective

Phase 3 converts the Phase-2 Medical Gate repair boundary into a Minimum Necessary Transformation generation contract. The outlier remains the packaging authority while current-project evidence remains the factual authority.

## Added runtime helpers

- `build_anchor_claim_map()` / `write_anchor_claim_map()` — cumulative Phase-1 claim-map support.
- `load_title_repair_blueprint()` — binds `13a_title_repair_blueprint.json` to the exact runtime anchor.
- `minimum_transformation_context()` — renders the Phase-3 writer constraints from the current project's Claim Map and Medical repair blueprint.

## Writer behavior

The Title Agent now freezes compliant anchor components by default, edits only the smallest unsupported span, recursively re-audits the complete repaired claim/title, permits empty fidelity tiers when safety requires it, and generates outward from the lowest-transformation safe neighborhood.

Tier bands are 0–10%, 10–20%, 20–35%, and controlled experimentation. They are fidelity bands rather than mandatory safety-overriding quotas.

## Selection boundary

Candidate generation is explicitly prohibited from choosing Winner, Safe Alternative, or High-Upside Experiment. Existing Judge/deterministic analysis remains authoritative for selection.

## Protected behavior

No changes were made to the Title V2 CSV schema, deterministic A/B/C classifier, >=8 anchor threshold, Content-Promise Bond, scoring formulas, Thumbnail, Script, Production, SEO, or CapCut systems.

## Acceptance behavior

For an unsafe condition-level anchor claim, a softer synonym is not automatically accepted. Every repaired complete claim must independently pass the current project's Research + Medical Gate 1 boundary. If no 0–10% repair passes, Tier 1 may be empty and quota migrates forward.

## Test Results

- Phase-3 focused tests: 6 passed.
- Full suite: 544 passed, 1 existing unrelated frozen A/B/C vocabulary expectation failed (`comfort` standalone token).
- The unrelated A/B/C semantic test was intentionally not changed.

## Cumulative Phase-2 contracts

Research Agent carries the neutral falsification mandate and Medical Agent carries the structured `13a_title_repair_blueprint.json` contract, so this ZIP is usable as the cumulative Anchor-First build through Phase 3.
