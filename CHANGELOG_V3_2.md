# V3.2 Change Log

## Updated application files
- `app.py`: V3.2 title/navigation, Advanced QA Dashboard, Apply Revisions controls, Writer Workspace quality metrics, automatic Production Cleaner preflight, Production Lock 2.0 display, and automatic prerequisite blocking/unlocking.
- `v31_core.py`: Auto Revision Engine, structured patch parser, safe patch application with timestamped backups, separate-output validation, Script Quality Metrics, Production Cleaner, QA Dashboard data, Production Lock 2.0 checklist, and automatic stage readiness.
- `config.json`: V3.2 feature flags and output-file configuration. Existing keys remain intact.

## Updated templates
- `Templates/Writing/opus_writer_prompt.md`: requires narration-only `06_final_script.md` and four separate writer reports.
- `Templates/Writing/narrative_qa_output_template.md`: adds PASS WITH REVISIONS and structured Revision Patch format.
- `Templates/medical_gate_2_output_template.md`: adds PASS WITH REVISIONS and structured Revision Patch format.

## Documentation
- Added `README_V3_2.md`.
- Updated `README.md` with a V3.2 reference.

## Tests
- Added revision parsing/application, backup, unmatched patch, separate report validation, Production Cleaner, quality metrics, stage progression, QA Dashboard and Production Lock 2.0 coverage.
