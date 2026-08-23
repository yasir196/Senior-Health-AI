# Senior Health AI System Audit

Audit date: 2026-07-17

Scope: `AGENT.md`, `PIPELINE_RUN_COMMANDS.md`, `config.json`, `Agents/`, relevant `System/` JSON files, current project output naming, production branches, and `PREVIOUS_CHAT_PROMPTS_EXTRACTED.md` as historical context only.

No existing files were modified during this audit.

## 1. Current Canonical Pipeline

The strongest current source of truth is `System/SYS_11_PIPELINE_DAG.json`, supported by `System/SYS_12_AGENTS.json`, `System/SYS_15_VALIDATION_GATES.json`, and `config.json`.

Current canonical order:

1. Project initialization
2. `Topic_Generator_Agent`
3. Human topic selection with `selected_topic_id`
4. `Outlier_Agent`
5. `Research_Agent`
6. `Medical_Agent` Gate 1
7. `Title_Agent`
8. `Thumbnail_Agent`
9. `Script_Agent`
10. Manual Claude Opus writing when `config.writer_mode = outline_to_script`
11. Narrative QA when `config.narrative_qa_enabled = true`
12. `Medical_Agent` Gate 2
13. Production mode decision from `config.production_mode`
14. Selected production branch only:
    - `talking_head`: `Production_TalkingHead_Agent`
    - `documentary`: `Production_Agent`
15. `SEO_Agent`
16. Final QA
17. Publish/schedule checklist
18. Project summary

Current config selects:

- `production_mode`: `talking_head`
- `writer_mode`: `outline_to_script`
- `narrative_qa_enabled`: `true`
- `voice_director_enabled`: `true`

Therefore the stable runtime path should currently be topic generation -> selected topic -> outlier -> research -> medical gate 1 -> titles -> thumbnails -> outline -> manual script -> narrative QA -> medical gate 2 -> speech optimizer -> talking-head production -> SEO -> final QA -> project summary.

## 2. Conflicting Stage Orders

`PIPELINE_RUN_COMMANDS.md` still contains older stage order in at least two places:

- Stage 1 command says `Topic input` then `Outlier_Agent / Opportunity Validation`, and creates only `01_topic_validation.md`.
- Full Pipeline command lists `Outlier_Agent / Opportunity Validation` before `Topic_Generator_Agent`.

This conflicts with:

- `AGENT.md`, which says Topic Intelligence comes before downstream work.
- `System/SYS_11_PIPELINE_DAG.json`, which requires `Topic_Generator_Agent` -> human topic selection -> `Outlier_Agent`.
- `System/SYS_12_AGENTS.json`, which blocks `outlier_agent` until `selected_topic_id` exists.

`System/SYS_11_PIPELINE_DAG.json` also declares `Title_Agent` and `Thumbnail_Agent` parallel after Medical Gate 1, but `Thumbnail_Agent` requires `03_titles.md`. That makes true parallel execution invalid unless thumbnail can run from finalist titles independently, which the current agent contract does not support.

## 3. Duplicate Or Outdated Instructions

`PIPELINE_RUN_COMMANDS.md` repeatedly tells Codex to read broad folders such as `Agents/`, `Knowledge/`, and `System/`. This conflicts with the context-efficient orchestration rule in `AGENT.md`, where only the active agent and its Required Inputs should be loaded.

`Agents/Production_TalkingHead_Agent.md` has older placeholder sections saying it creates only `11_talkinghead_production.md` and must not create other project files. Later in the same file, `Editor CSV Output` requires `12_talkinghead_editor.csv`. The later contract appears newer, but the older text remains contradictory.

`Agents/Stable/Thumbnail_Agent_v1.0.md` is a frozen historical/stable variant, while `Agents/Thumbnail_Agent.md` is the active agent. The stable file includes different concept count and scoring philosophy than the active thumbnail engine. Its status is not documented in `SYS_12_AGENTS.json`, so it is orphaned unless intentionally kept as an archive.

`PIPELINE_RUN_COMMANDS.md` contains legacy commands such as `Revise Titles Only`, `Revise Thumbnail Only`, and `Revise Script Only` that are useful, but some still reference broad folder loading and older expectations.

## 4. Missing Dependencies

`Outlier_Agent.md` does not list the current required upstream files:

- `Projects/<topic_slug>/00_topic_ideas.md`
- `Projects/<topic_slug>/00_topic_ideas.csv`
- `selected_topic_id`

Instead it still lists a raw topic string and target folder path. This conflicts with the DAG and agent registry.

`System/SYS_15_VALIDATION_GATES.json` requires `Projects/<topic_slug>/07_script_validation.md` in `production_readiness`, but no active agent or pipeline command creates that file. Historical prompts mention `Final_Script_Validation_Agent`, but no active agent file exists for it.

Narrative QA has no dedicated active agent, no clearly owned output file, and no single storage location for PASS/PASS WITH SUGGESTIONS/FAIL. `PIPELINE_RUN_COMMANDS.md` says Narrative QA may update `13_fact_check_log.md`; the speech optimizer command expects Narrative QA status in `09_qa_checklist.md`; Final QA also owns `09_qa_checklist.md`.

`Production_TalkingHead_Agent.md` optional inputs include `09_voice_direction.md` and `10_final_timestamps.md`, but those files are not part of the canonical expected output list and no active stage creates them.

## 5. Output File Mismatches

`AGENT.md` expected completed project files still list documentary production outputs:

- `07_production_sheet.csv`
- `10_image_prompts.md`
- `12_broll_prompts.md`

But current `config.json` selects `talking_head`, and `System/SYS_15_VALIDATION_GATES.json` says unselected branch outputs are not required. `AGENT.md` does not list the talking-head outputs as expected files:

- `11_talkinghead_production.md`
- `12_talkinghead_editor.csv`

Current project output naming includes `05a_opus_handoff.md`, but `AGENT.md` and `PIPELINE_RUN_COMMANDS.md` expect `opus_writer_package.md`. Historical prompts also used `06_opus_handoff.md`. These are three competing names for the external writer handoff.

Current project output includes `08_editor_sheet.xlsx`, but the canonical pipeline does not list it as a stable required or optional branch output.

`09_qa_checklist.md` and `14_project_summary.md` are expected by `AGENT.md` and `PIPELINE_RUN_COMMANDS.md`, but the inspected project folder does not currently contain them.

## 6. Agent Input/Output Mismatches

`System/SYS_12_AGENTS.json` lists `script_agent` outputs as both `05_script_outline.md` and `06_final_script.md`. This is only true when `writer_mode` is not `outline_to_script`. With the current `config.json`, `Script_Agent.md` correctly says it must create only `05_script_outline.md` and stop.

`System/SYS_11_PIPELINE_DAG.json` lists script output as `05_script_outline.md + 06_final_script.md`, but the current writer mode makes `06_final_script.md` a manual external deliverable.

`SEO_Agent.md`, `System/SYS_11_PIPELINE_DAG.json`, and `System/SYS_12_AGENTS.json` require `07_production_sheet.csv` as the SEO production input. This works for documentary mode, but not for the selected talking-head branch, which creates `11_talkinghead_production.md` and `12_talkinghead_editor.csv`.

`Thumbnail_Agent.md` requires `03_titles.md`, while the DAG attempts to run thumbnail in parallel with title after Medical Gate 1. The agent contract makes thumbnail dependent on title completion.

`Research_Agent.md` creates only `02_research_sheet.md`, while several run prompts historically ask research plus medical gate together to create both `02_research_sheet.md` and `13_fact_check_log.md`. That is acceptable if orchestrated as two stages, but should not be described as a single `Research_Agent` output.

## 7. Talking Head Vs Documentary Branch Conflicts

The branch model is correctly represented in `System/SYS_11_PIPELINE_DAG.json`, `System/SYS_15_VALIDATION_GATES.json`, and `config.json`.

However, the rest of the repository is not fully branch-aware:

- `AGENT.md` completed project output list is documentary-first and does not include talking-head outputs.
- `SEO_Agent.md` requires documentary production sheet even when talking-head is selected.
- `System/SYS_12_AGENTS.json` registers `production_agent` but does not register `production_talkinghead_agent`.
- `PIPELINE_RUN_COMMANDS.md` has documentary production commands but no canonical talking-head production command.
- `Production_TalkingHead_Agent.md` internally conflicts on whether it may create one file or two files.
- `System/SYS_15_VALIDATION_GATES.json` correctly says talking-head must not require documentary outputs, but other files still do.

Because `config.production_mode` is currently `talking_head`, these conflicts are operational, not theoretical.

## 8. Narrative QA And Final QA Conflicts

Narrative QA is described as a required pre-production gate, but ownership is unclear:

- `AGENT.md` requires Narrative QA before Medical Gate 2 and production.
- `PIPELINE_RUN_COMMANDS.md` defines a Narrative QA command using `Templates/Writing/opus_narrative_qa.md`.
- No active `Narrative_QA_Agent.md` exists.
- No canonical Narrative QA output file is declared.

Final QA is described as an orchestrator stage creating `09_qa_checklist.md`, but the speech optimizer command also expects Narrative QA PASS/PASS WITH SUGGESTIONS in `09_qa_checklist.md`. That means `09_qa_checklist.md` is being used for both pre-production narrative QA and final publishing QA unless a clear section contract is added.

`System/SYS_15_VALIDATION_GATES.json` defines `production_readiness` and `publishing_readiness`, which is the right separation, but `PIPELINE_RUN_COMMANDS.md` and `AGENT.md` do not fully separate these readiness scopes in their expected file lists.

## 9. Unused Or Orphaned Agents/Files

Potentially orphaned or unclear files:

- `Agents/Stable/Thumbnail_Agent_v1.0.md`: archived/frozen version, not registered in `SYS_12_AGENTS.json`.
- `Agents/Telemetry_Agent.md`: active advisory agent, but not part of the current canonical production DAG.
- `System/SYS_16_TELEMETRY.json` and `System/SYS_16_TELEMETRY_ENGINE.json`: duplicate-looking telemetry files; current agent reads engine plus self-improvement files.
- `System/SYS_17_SELF_IMPROVEMENT.json` and `System/SYS_17_SELF_IMPROVEMENT_ENGINE.json`: duplicate-looking self-improvement files.
- `System/SYS_13_PROMPT_LIBRARY.json`: referenced by some agents indirectly through `Knowledge/13_Prompt_Library.md`, but not clearly owned in the DAG.
- `Projects/<topic_slug>/05a_opus_handoff.md`: exists, but does not match current `opus_writer_package.md` naming.
- `Projects/<topic_slug>/08_editor_sheet.xlsx`: exists, but is not part of the current canonical branch outputs.
- `PREVIOUS_CHAT_PROMPTS_EXTRACTED.md`: useful history, but not a source of truth for current workflow.

## 10. Recommended Exact Files To Update

Update these files first:

1. `PIPELINE_RUN_COMMANDS.md`
   - Replace old Stage 1 and Full Pipeline order.
   - Remove broad folder-loading instructions.
   - Add canonical talking-head run command.
   - Make Narrative QA and Final QA output ownership explicit.

2. `Agents/Outlier_Agent.md`
   - Replace raw topic input with `00_topic_ideas.md`, `00_topic_ideas.csv`, and `selected_topic_id`.
   - Align Required Inputs with `System/SYS_11_PIPELINE_DAG.json` and `System/SYS_12_AGENTS.json`.

3. `System/SYS_12_AGENTS.json`
   - Register `production_talkinghead_agent`.
   - Make script output conditional on `writer_mode`.
   - Make SEO input conditional on selected production branch.

4. `Agents/Production_TalkingHead_Agent.md`
   - Remove or revise older "only `11_talkinghead_production.md`" language.
   - Keep the current two-file output contract if talking-head branch remains selected.

5. `Agents/SEO_Agent.md`
   - Allow production input from either documentary outputs or talking-head outputs based on `config.production_mode`.
   - Do not require `07_production_sheet.csv` when `talking_head` is selected.

6. `AGENT.md`
   - Make the expected output list branch-aware.
   - Clarify that `06_final_script.md` is external/manual when `writer_mode = outline_to_script`.
   - Add or clarify canonical Narrative QA output location.

7. `System/SYS_11_PIPELINE_DAG.json`
   - Remove invalid title/thumbnail parallelism unless `Thumbnail_Agent` no longer requires `03_titles.md`.
   - Make script output conditional on writer mode.
   - Make SEO input branch-aware.

8. `System/SYS_15_VALIDATION_GATES.json`
   - Remove or define ownership for `07_script_validation.md`.
   - Clarify whether Narrative QA is part of `production_readiness`, where it is recorded, and how it differs from Final QA.

9. `Agents/Script_Agent.md`
   - Align default runtime wording with `config.json` target `25` and range `23-28`, or make the config override more prominent than the older 18-23 default language.

10. `System/SYS_06_THUMBNAIL_ENGINE.json` and `Agents/Thumbnail_Agent.md`
   - Decide whether active thumbnail generation is 10 concepts or stable v1-style 5 concepts. Current active files agree on 10, but historical/stable file differs.

## Critical Fixes

1. Fix stage order in `PIPELINE_RUN_COMMANDS.md`: Topic Generator must run before Outlier, and human topic selection must exist before Outlier.
2. Fix `Outlier_Agent.md` Required Inputs to match DAG-selected topic workflow.
3. Fix talking-head branch handoff to SEO: `SEO_Agent.md`, `SYS_11_PIPELINE_DAG.json`, and `SYS_12_AGENTS.json` currently assume documentary `07_production_sheet.csv`.
4. Fix `Production_TalkingHead_Agent.md` internal output contradiction so the selected branch has one clear contract.
5. Define Narrative QA output ownership and stop using `09_qa_checklist.md` ambiguously for both Narrative QA and Final QA unless explicitly sectioned.
6. Resolve `07_script_validation.md`: either create a real owning stage/agent or remove it from `SYS_15_VALIDATION_GATES.json`.
7. Remove invalid Title/Thumbnail parallelism or change Thumbnail inputs. Current thumbnail requires `03_titles.md`.

## Recommended Fixes

1. Make `AGENT.md` expected output list branch-aware for `talking_head` vs `documentary`.
2. Make `SYS_12_AGENTS.json` conditional for script outputs under `writer_mode = outline_to_script`.
3. Add a canonical talking-head production command to `PIPELINE_RUN_COMMANDS.md`.
4. Standardize Opus handoff naming: choose one of `opus_writer_package.md`, `05a_opus_handoff.md`, or `06_opus_handoff.md`.
5. Update `Script_Agent.md` runtime language so config `23-28` is clearly the active default.
6. Mark `Agents/Stable/Thumbnail_Agent_v1.0.md` as archive-only or register it as a selectable stable agent, but not both.

## Optional Cleanup

1. Document whether `Telemetry_Agent` is outside the production DAG by design.
2. Consolidate duplicate-looking telemetry/self-improvement JSON files or document which ones are active.
3. Decide whether `08_editor_sheet.xlsx` is an official output, optional editor package, or historical artifact.
4. Add a short `SYSTEM_SOURCE_OF_TRUTH.md` or section in `AGENT.md` identifying the authoritative files in priority order.
5. Keep `PREVIOUS_CHAT_PROMPTS_EXTRACTED.md` as historical context only and exclude it from runtime orchestration.

## Proposed Stable Pipeline

1. Topic intelligence: `Topic_Generator_Agent` creates `00_topic_ideas.md` and `00_topic_ideas.csv`.
2. Human gate: user selects `selected_topic_id`.
3. Opportunity validation: `Outlier_Agent` creates `01_topic_validation.md` and `01b_outlier_references.md`.
4. Research: `Research_Agent` creates `02_research_sheet.md`.
5. Medical Gate 1: `Medical_Agent` updates `13_fact_check_log.md`.
6. Title: `Title_Agent` creates `03_titles.md` and `03_titles.csv`.
7. Thumbnail: `Thumbnail_Agent` creates `04_thumbnail_concepts.md` and `11_thumbnail_prompt.md`.
8. Script outline: `Script_Agent` creates `05_script_outline.md`.
9. Manual writer: external Claude Opus creates `06_final_script.md` when `writer_mode = outline_to_script`.
10. Narrative QA: record PASS/PASS WITH SUGGESTIONS/FAIL in one canonical pre-production QA location.
11. Medical Gate 2: `Medical_Agent` updates `13_fact_check_log.md`.
12. Speech optimizer when enabled: create `06a_voice_script.md` and `06b_voice_checklist.md`.
13. Production mode decision from `config.production_mode`.
14. If `talking_head`: `Production_TalkingHead_Agent` creates `11_talkinghead_production.md` and `12_talkinghead_editor.csv`.
15. If `documentary`: `Production_Agent` creates `07_production_sheet.csv`, `10_image_prompts.md`, and `12_broll_prompts.md`.
16. SEO: `SEO_Agent` reads the selected branch output and creates `08_youtube_metadata.md`.
17. Final QA: orchestrator creates or updates `09_qa_checklist.md`.
18. Project summary: orchestrator creates `14_project_summary.md`.
