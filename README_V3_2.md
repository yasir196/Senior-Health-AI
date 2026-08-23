# Senior Health AI V3.2

V3.2 preserves the V3.1 architecture, project folders, filenames, agents, templates, Manual Writing Workflow, Writer Workspace, configuration and Direct Codex Run.

## V3.2 upgrades

- Auto Revision Engine reads structured Revision Patch blocks from Narrative QA and Medical Gate 2 reports. Apply Revisions updates `06_final_script.md` and first creates a timestamped backup in `Backups/`.
- Writer outputs are separated into `06_final_script.md`, `06_runtime_report.md`, `06_retention_report.md`, `06_medical_review.md`, and `06_humanization_report.md`. The final script contains narration only.
- Production Cleaner normalizes Markdown, removes `Copy[Visual Cue]`, validates Visual Cue blocks and headings, trims whitespace, creates a backup when it changes the script, and writes `production_clean_report.md`.
- Advanced QA Dashboard shows Narrative QA, Medical Gate 2, Speech Optimizer, and Production Cleaner status and issue counts, with report viewing.
- Writer Workspace displays sentence, paragraph, repetition, contractions, read-aloud, ElevenLabs pause, rhetorical question, WPM, section runtime, and reading difficulty metrics.
- Production Lock 2.0 checks Hook, Runtime, CTA, Host Identity, Medical Safety, Humanization, Curiosity Loops, Visual Cue Validation, Production Cleaner, Narrative QA, Medical Gate 2, and Speech Optimizer.
- Auto Stage Progression unlocks downstream stages only when upstream outputs pass.

## Revision Patch format

```text
### Revision 1
Section: Hook
Current Text: exact text from the script
Replace With: corrected text
Reason: why this change is required
Severity: HIGH
```

Exact Current Text matching protects formatting and prevents unsafe broad replacements. Unmatched items are reported and skipped.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Tests

```bash
pytest -q
python -m compileall -q .
```

## V3.2 Usability and Reliability Update

The existing V3.2 architecture and workflow remain unchanged. Writer Workspace now presents actionable script-quality information without modifying narration: read-aloud component scores and target ranges, contraction opportunities, expandable repeated-opening locations, total/video runtime, per-section runtime, and long-section warnings.

Script validation accepts either the semantic heading structure (`Hook`, `Introduction`, `Main Content`, `Conclusion`) or the legacy numbered structure containing `Section 1` through `Section 11`. Production Lock failures now include specific remediation reasons. The QA Dashboard shows colored status badges, issue counts, report modification time, report filename, and quick report opening controls.

## Gate status synchronization

V3.2 uses one disk-backed `get_gate_status(project, gate_name, config)` helper for Narrative QA, Medical Gate 2, QA Dashboard, Dashboard, Speech Optimizer, Production Lock, and Production readiness. The helper reads the current report file on every call, normalizes Markdown/whitespace, and supports `PASS`, `PASS WITH REVISIONS`, `PASS WITH SUGGESTIONS`, and `FAIL`. No Streamlit session value is used as a gate-status source. Speech Optimizer requires an exact `PASS` from both Narrative QA and Medical Gate 2.

## Production Cleaner integration fix

Production Cleaner is integrated directly into the existing Production Lock and Production views; no new sidebar page or workflow stage was added.

- The production narration source is `06a_voice_script.md` (or the existing `voice_script_suffix` configuration value).
- Narrative QA and Medical Gate 2 must both be exactly `PASS`, and `06a_voice_script.md` plus `06b_voice_checklist.md` must exist before the cleaner runs.
- Opening Production Lock automatically runs the cleaner when the report is missing or stale.
- A visible **Run Production Cleaner** / **Run Production Cleaner Again** control is also available in the existing lock flow.
- Permitted cleanup is limited to Markdown spacing, blank-line/trailing-whitespace normalization, `Copy[Visual Cue]` normalization, and Visual Cue formatting validation.
- `06_final_script.md` is never modified by Production Cleaner.
- When `06a_voice_script.md` requires formatting changes, a timestamped copy is created in `Backups/` before replacement.
- `production_clean_report.md` records PASS/FAIL, source filename, source SHA-256, timestamp, changes, and human-readable issues.
- A previous PASS report becomes stale whenever the production source hash changes; Production remains locked until the cleaner reruns successfully.

## Production Cleaner voice-script validation correction

Production Cleaner validates the Speech Optimizer output (`06a_voice_script.md`) as plain narration. It no longer requires Markdown headings. Instead it rejects Markdown/headings, Visual Cue blocks, editor or QA notes, SSML, bracket tags, and missing CTA/host identity when those elements are present in `06_final_script.md`. Automatic cleanup is limited to whitespace normalization, so narration wording and medical meaning are not changed.

## Production page reliability fix

The Production page now uses the shared `count_words()` utility to estimate runtime from `06a_voice_script.md`. The page provides a visible **Generate Production Plan** action that invokes the existing Production Package runner without changing Direct Codex Run. Generation is enabled only when Production Lock is READY, the production mix totals exactly 100%, and the configured Codex CLI is available. The page verifies and exposes the existing outputs: `07_production_sheet.csv`, `10_image_prompts.md`, and `12_broll_prompts.md`.
