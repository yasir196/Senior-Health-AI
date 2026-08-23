# Evidence Library

This folder stores reusable evidence for Senior Health AI projects.

The library is managed by `Knowledge/16_Evidence_Library_Manager.md` and `System/SYS_18_EVIDENCE_LIBRARY.json`.

## Files

- `evidence_sources.csv` stores vetted sources.
- `claim_registry.csv` stores reusable claim wording and caveats.
- `topic_index.md` helps Research_Agent find existing sources quickly.
- `review_queue.csv` tracks stale, uncertain, or to-be-checked entries.

## Use Rules

Research_Agent must check this folder before doing new research.

Medical_Agent must cross-check project claims against this folder, but the library never creates an automatic pass. Every project still needs:

- `02_research_sheet.md`
- `13_fact_check_log.md`

Only sources with status `approved` may be reused directly. Sources marked `needs_review` can guide research but must be checked before use.

The library cannot override `System/SYS_09_MEDICAL_RULE_ENGINE.json`.
