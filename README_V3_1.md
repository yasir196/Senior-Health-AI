# Senior Health AI V3.1

V3.1 is an in-place, editable upgrade of V3. Existing projects and file names remain compatible.

## Added in V3.1

- **Narrative QA:** dedicated workflow and report status detection from `14_narrative_qa.md`.
- **Medical Gate 2:** dedicated UI, evidence prerequisites, direct Codex execution, and report display.
- **Speech Optimizer:** creates `06a_voice_script.md` and `06b_voice_checklist.md` only after both QA gates pass.
- **Improved Workflow UI:** bounded stages, project validation, last-run information, and stage-specific Direct Codex Run.
- **Dashboard Progress:** weighted progress, next action, gate status, production readiness, and project-level workflow cards.
- **Production Lock:** blocks Production Package until Final Script, Narrative QA, Medical Gate 2, and required speech outputs are ready.
- **Direct Codex Run:** configurable CLI template, persistent run logs in `RunLogs/`, per-project `.last_run.json`, timeout/error handling.
- **V3.1 Core:** shared logic in `v31_core.py` prevents dashboard, workflow, and production pages from applying different rules.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

On Windows, the default Codex command is:

```text
codex.cmd exec --sandbox workspace-write --skip-git-repo-check {prompt}
```

Codex CLI must be installed and logged in. You can change the command in **Config**. The template must contain `{prompt}`; `{project}` is optional.

## Gate report contract

Narrative QA and Medical Gate 2 reports should include one explicit line:

```text
Status: PASS
```

Accepted statuses are `PASS`, `PASS WITH SUGGESTIONS`, and `FAIL`. Missing or unclear statuses keep Production Lock active.

## Production Lock requirements

By default, Production Package requires:

1. `06_final_script.md`
2. `14_narrative_qa.md` with a passing status
3. `15_medical_gate_2.md` with a passing status
4. `06a_voice_script.md`
5. `06b_voice_checklist.md`

Speech enforcement can be changed in `config.json` or Config UI through `speech_optimizer_required_for_production`.

## Editable source

All Python, Markdown, JSON, CSV, templates, agents, project files, tests, and configuration remain included. No compiled-only application is used.

## V3.1 Manual Writing Workflow

The workflow now includes **Writer Workspace** between **Prepare Opus Package** and **Narrative QA**:

1. Complete `05_script_outline.md`.
2. Run **Prepare Opus Package** to create `opus_writer_package.md`.
3. Open **Writer Workspace**, select the project, and download the Opus package.
4. Use the package in Claude to write the complete script.
5. Upload a UTF-8 `.md` or `.txt` file. The workspace stores it as `06_final_script.md`.
6. Existing scripts require UI confirmation and are automatically copied to `Backups/` before replacement.
7. Narrative QA remains blocked until the final script passes file, minimum length, Markdown heading, and basic CTA/medical-safety checks.

Writer Workspace displays word count, estimated narration runtime, configured target range, validation issues, and a script preview. Upload events are appended to the project `.manual_events.jsonl`, mirrored to `RunLogs/manual_events.jsonl`, and reflected in `.last_run.json`.

### Writer configuration

```json
{
  "narration_words_per_minute": 145,
  "writer_minimum_words": 300,
  "writer_required_headings": ["Hook", "Introduction", "Main Content", "Conclusion"],
  "writer_backup_on_overwrite": true
}
```

Dashboard weighted progress, next-action logic, stage registry, Narrative QA prerequisites, and Production Lock all use the same validation rules from `v31_core.py`.
