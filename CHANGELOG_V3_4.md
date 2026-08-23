# Senior Health AI V3.4

- Added generic `timeline_builder.py`; it is the sole reader of `08_actual_timeline.csv`.
- Added isolated `capcut_export.py`; it consumes only `timeline_manifest.json`.
- Added deterministic CapCut Desktop plain-JSON draft generation with V1/V2/V3/A1 tracks.
- Added image and B-roll placeholder references for every scene.
- Added Production-page **Generate CapCut Project** action after Avatar Timing outputs.
- Supported interoperability target: CapCut Desktop 6.x-9.x plain-JSON draft schema, version marker 9.0.0.
- Avatar Timing Sync, prompts, Direct Codex Run, project structure, and timeline CSV schema are unchanged.

## Timeline time parser fix

- Added one shared `parse_timeline_time(value)` helper in `timeline_builder.py`.
- Supports numeric seconds, `MM:SS[.fraction]`, and `HH:MM:SS[.fraction]`.
- Timeline start/end remain the placement source of truth.
- Duration CSV values are validated as numeric seconds with a configurable 0.15-second default tolerance.
- Added coverage for live Avatar Timing timestamp formats and rounded duration rows.

## Zero-duration scene boundary fix

- Resolved adjacent scene-boundary collisions globally using existing transcript word timestamps.
- Ensured every narrated scene receives a positive, chronological, non-overlapping word interval.
- Added pre-write validation that blocks zero or negative durations with scene ID, start, end, duration, and narration text.
- Added S155 regression coverage and full-timeline positive-duration validation.

## Avatar asset path resolution fix

- Added one explicit `project_root` for the complete CapCut export operation.
- Added shared `resolve_asset_reference()` and `validate_manifest_assets()` helpers.
- Project-relative avatar, image, and B-roll references now resolve only against the project root.
- Absolute paths remain supported; Windows and forward-slash relative paths are normalized with `pathlib`.
- CapCut materials now use the resolved source-avatar path.
- Asset manifest and export report include manifest reference, resolved path, project root, and existence status.
- Timeline Builder splits avatar range labels such as `c1.mp4 to c2.mp4` into separate portable references.
- No source media is copied or modified during validation.

## Optional CapCut placeholder validation fix

- Required avatar assets remain hard requirements.
- Missing placeholder images and B-roll are warning-only.
- Missing optional placeholders remain in timeline/asset/report metadata but are omitted from CapCut materials and tracks.
- Existing optional image and B-roll files are included normally.
- Export reports separate required avatar missing, optional image missing, optional B-roll missing, and optional included counts.
- Production UI reports successful generation with optional-assets warnings instead of a required-avatar error.
- Avatar range references remain split and are validated as separate files.

## CapCut Desktop 8.7 complete draft bundle

- Replaced the two-file-only export with a deterministic CapCut Desktop 8.7 Windows multi-file draft bundle.
- Added root metadata/default files: `draft_agency_config.json`, `draft_biz_config.json`, `attachment_pc_common.json`, `performance_opt_info.json`, `timeline_layout.json`, and `draft_settings`.
- Added auxiliary directories: `Resources/`, `Timelines/`, `subdraft/`, `adjust_mask/`, `common_attachment/`, `matting/`, `smart_crop/`, and `qr_upload/`.
- Added synchronized timeline mirrors at `Timelines/<timeline-id>/draft_content.json` and `template-2.tmp` so modern CapCut storage targets cannot diverge from the root timeline.
- Added deterministic draft/timeline UUID relationships and schema/app version markers for CapCut Desktop 8.7 Windows.
- Added pre-return bundle validation for mandatory files, directories, timeline relationship paths, and byte-identical timeline mirrors.

## Live CapCut 8.7 sync and planning-slot fix
- V1/A1 now use authoritative avatar_timing_manifest.json chunk ranges, one segment per avatar chunk.
- Removed scene-level avatar/audio slicing from CapCut export.
- Timeline Builder embeds base avatar timing and production-sheet visual assignments into timeline_manifest.json.
- AI-image and STOCK_VIDEO slots are created only for assignments in 07_production_sheet.csv.
- Missing assigned visuals receive deterministic visible local PNG planning placeholders on V2/V3.
- Real assets replace placeholders automatically on rerun.
- Export report distinguishes PROJECT GENERATED / PREVIEW READY from FINAL ASSETS READY and includes per-chunk sync diagnostics.

## System-Level Semantic Visual Diversity Upgrade
- Replaced shallow prompt-variation diversity guidance with Core Visual Signatures weighted toward narrative purpose, subject, action, object relationship, archetype, and metaphor.
- Added dynamic project-local visual-family discovery and project-local ledger reset requirements.
- Added config-driven rolling repetition, semantic similarity, family-share, composition/action/object-relationship thresholds.
- Added alternative-concept rewrites that must change visual strategy rather than camera/location/lighting only.
- Added explicit intentional-continuity justification requirements and expanded semantic Visual Diversity QA metrics/fail conditions.
- Preserved Production Mix, image assignments/counts/naming, actual timeline timing, CapCut behavior, Avatar Timing, medical/narrative gates, B-roll, and overlays.
- Added topic-agnostic regression contract tests. Full suite: 242 passed.


## Final Semantic Coherence Guard

- Added a mandatory post-diversity Semantic Coherence Guard before `10_image_prompts.md` finalization.
- Coherence validation now checks narration relevance, setting/action and time compatibility, object/location compatibility, narrative purpose, emotional tone, structural narration roles, and real-world plausibility.
- Diversity rewrites are rechecked against original Script Context, Narrative Context, preceding visual, and following visual; incoherent rewrites are rejected and corrected within configurable bounds.
- Final image prompts now require simultaneous `Overall Visual Diversity: PASS` and `Overall Semantic Coherence: PASS`.
- Production Mix, image counts, filenames, timings, CapCut mapping, Avatar Timing, and other workflow stages remain unchanged.


## Visual Diversity Finalization + Final-Prompt Semantic Coherence Fix

- Visual Diversity convergence now treats unresolved near-duplicate candidates as a hard finalization blocker and reports exact unresolved image IDs at retry exhaustion.
- Semantic Coherence now parses the final rendered prompt itself and checks temporal/lighting, setting/action, object/location, narrative-purpose, structural-role, and emotional-tone compatibility.
- CTA/subscribe/sign-off/episode-close narration is isolated as STRUCTURAL when appropriate and does not inherit recurring topic imagery without narration support.
- `10_image_prompts.md` now exposes `Production Ready: YES/NO`; YES requires both Visual Diversity PASS and Semantic Coherence PASS.
- Regenerated included 74-image project output with 0 near-duplicate candidates and both QA gates PASS while preserving filenames, scene assignments, counts, and timing.

## Semantic Coherence Final-Output Verification Fix
- Added topic-agnostic deterministic final-prompt semantic verification (`semantic_coherence.py`).
- Final rendered prompt text is re-audited for temporal contradictions and structural-close inheritance after all rewrites.
- Host/episode terminal narration is classified as `STRUCTURAL_CLOSE` before final prompt generation.
- A stale Semantic Coherence PASS is overridden to FAIL with exact IMAGE IDs and `Production Ready: NO` when final conflicts remain.
- Visual Diversity logic, thresholds, signatures, convergence, assignments, filenames, scene mapping, timing, and CapCut behavior are unchanged.
