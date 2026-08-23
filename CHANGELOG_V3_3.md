# V3.3 Changelog

- Extended the existing Production page with Avatar Timing Sync.
- Added avatar chunk discovery with scene-name preference and duplicate/unsupported reporting.
- Added OpenAI verbose transcription adapter with SRT and word-timing JSON preservation.
- Added fingerprint cache for unchanged chunks.
- Added approved narration/transcript alignment and confidence scoring.
- Added `08_actual_timeline.csv`, `avatar_timing_manifest.json`, and `avatar_alignment_report.md`.
- Added automated coverage for successful generation, missing/duplicate chunks, failures, low alignment, Production Lock blocking, and cache reuse.
- Preserved V3.2 workflow, pages, agents, prompts, filenames, and Direct Codex Run.
- Added deterministic transcription-model resolution: `OPENAI_TRANSCRIPTION_MODEL` → config → `whisper-1`.
- Added preflight capability validation; incompatible models fail clearly and never silently fall back.
- Kept `whisper-1` as the default because Avatar Timing Sync requires `verbose_json` with segment and word timestamps.
- Added effective model/settings to transcript cache metadata, manifest, alignment report, and Production-page status.
- Invalidated cached transcripts when model, response format, timestamp granularities, language, or media fingerprint changes.
- Preserved all V3.3 output filenames and schemas; model metadata is additive only.

## Automatic chunk discovery and global timing fix

- Removed production-scene-derived avatar chunk expectations.
- Detects an unlimited contiguous `c1` through `cN` sequence from the selected folder.
- Sorts chunks numerically so `c10` follows `c9`.
- Reports missing numeric chunk gaps without assigning unrelated media.
- Concatenates all transcripts in chunk order and applies cumulative offsets to word and segment timestamps.
- Supports many production scenes per avatar chunk and scene timing across chunk boundaries.
- Keeps cache, SRT, JSON, manifest, alignment report, and timeline output compatibility.


## Avatar Timing Sync transcription reliability fix

- Added persistent Production-page traceback reporting and `avatar_transcription_error.log`.
- Added pre-flight validation and per-chunk status table.
- Added automatic FFmpeg mono MP3 extraction for video/oversized media.
- Added source/extracted duration integrity checks and extraction-aware cache metadata.
- Changed batch failures to stop safely while retaining completed transcript outputs.

## Narrative QA Single-Cycle Runtime Convergence

- Narrative QA now calculates spoken narration words only, excluding headings, Markdown, visual cues, scene labels, and production notes.
- Runtime analysis reads the configured target, allowed range, and narration WPM from `config.json`.
- Runtime-only revision patches must be sized to converge inside the configured range in one rewrite pass rather than using incremental expansion or compression.
- Added required `## Runtime Analysis` projection fields and projected-runtime status logic.
- Updated the Direct Codex Narrative QA command and output template to enforce the same behavior.


## Narrative QA Runtime Convergence Guard
- Runtime-only revisions now target the midpoint of the configured range instead of either boundary.
- Added minimum/target/maximum/midpoint calculations, projected-runtime simulation, ±5% midpoint guard, and an explicit Convergence Check.
- Narrative QA must rebalance oversized or undersized patches internally before output, preventing expansion/compression oscillation.
