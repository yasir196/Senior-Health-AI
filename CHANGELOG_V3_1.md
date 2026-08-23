# V3.1 Changelog

## Application
- Added shared `v31_core.py` orchestration and validation layer.
- Upgraded branding and navigation to Senior Health AI V3.1.
- Added dedicated Medical Gate 2, Speech Optimizer, and Production Lock pages.
- Reworked Workflow with bounded Direct Codex Run, validation, persistent logs, and last-run status.
- Reworked Dashboard with weighted progress, next action, gate status, and production readiness.

## Safety and workflow integrity
- Production Package is blocked until required upstream gates pass.
- Gate reports require an explicit PASS, PASS WITH SUGGESTIONS, or FAIL status.
- Speech outputs are required by default before production and are configurable.
- Existing project names and output filenames remain compatible.

## Testing
- Added V3.1 tests for report parsing, production locking, failed gates, and weighted progress.
- Full suite result: 96 passed.
