# 12 - AI Agent Workflows

> Permanent internal documentation. Senior Health YouTube Production System.
> This document is standalone and self-contained.

---

## 1. Agent Roster

| Agent | Purpose | Primary Output | Can Block Pipeline |
|---|---|---|---|
| Outlier_Agent | Validate opportunity and strategic fit | `01_topic_validation.md` | Yes |
| Research_Agent | Gather evidence, mechanism, contraindications | `02_research_sheet.md` | Yes |
| Medical_Agent | Run Gate 1 and Gate 2 medical review | `13_fact_check_log.md` | Yes |
| User-Supplied Winning Title | `project.json.anchor_title` is immutable; no title generation stage | `project.json` | Yes |
| Thumbnail_Agent | Create thumbnail concepts and final thumbnail prompt | `04_thumbnail_concepts.md`, `11_thumbnail_prompt.md` | Yes |
| Script_Agent | Write outline and final script | `05_script_outline.md`, `06_final_script.md` | Yes |
| Production_Agent | Build timed production sheet and prompt banks | `07_production_sheet.csv`, `10_image_prompts.md`, `12_broll_prompts.md` | Yes |
| SEO_Agent | Prepare metadata and publishing package | `08_youtube_metadata.md` | Yes |
| Orchestrator | Run Final QA, publish checklist, project summary | `09_qa_checklist.md`, `14_project_summary.md` | Yes |

---

## 2. Canonical Automation Workflow

User-supplied Anchor / Outlier Title -> Outlier_Agent validation -> Research_Agent -> Medical_Agent Gate 1 -> Thumbnail_Agent -> Script_Agent -> Medical_Agent Gate 2 -> Production_Agent -> SEO_Agent -> Final QA -> Publish/Schedule checklist -> Project Summary.

There is no Title_Agent stage. After Medical Gate 1, Thumbnail_Agent uses the immutable winning title from `project.json.anchor_title`; Script_Agent uses that same title. Medical_Agent maintains `13_fact_check_log.md` across both medical gates.

---

## 3. Handoff Contract

Each agent must write its output to `Projects/<topic_slug>/` and the next agent must read that output before acting.

| From | Output | To | Used As Input For |
|---|---|---|---|
| Topic input | Topic string | Outlier_Agent | Opportunity validation |
| Outlier_Agent | `01_topic_validation.md` | Research_Agent | Research scope and strategic fit |
| Evidence Library Manager | `Evidence/evidence_sources.csv`, `Evidence/claim_registry.csv` | Research_Agent, Medical_Agent | Reusable source and claim cross-check |
| Research_Agent | `02_research_sheet.md` | Medical_Agent Gate 1 | Claim verification |
| Medical_Agent Gate 1 | `13_fact_check_log.md` gate entry and Evidence Library cross-check | Thumbnail_Agent | Safe packaging boundaries for the immutable user-supplied winning title |
| Winning Title | `project.json.anchor_title` | Thumbnail_Agent, Script_Agent, SEO_Agent | Immutable user-supplied title promise |
| Thumbnail_Agent | `04_thumbnail_concepts.md`, `11_thumbnail_prompt.md` | Script_Agent, Production_Agent | Visual promise and hero object |
| Script_Agent | `05_script_outline.md`, `06_final_script.md` | Medical_Agent Gate 2 | Script fact-check |
| Medical_Agent Gate 2 | updated `13_fact_check_log.md` | Production_Agent | Production permission |
| Production_Agent | `07_production_sheet.csv`, `10_image_prompts.md`, `12_broll_prompts.md` | SEO_Agent, Final QA | Asset and edit plan |
| SEO_Agent | `08_youtube_metadata.md` | Final QA | Publishing package |
| Final QA | `09_qa_checklist.md` | Publish/Schedule | Go/no-go |
| Publish/Schedule | Publish status | Project Summary | Final package status |
| Project Summary | `14_project_summary.md` | User / next run | Final handoff |

---

## 4. Failure Routing

- Research fail -> Research_Agent
- Medical Gate 1 fail -> Research_Agent
- User-supplied title validation fail -> stop and report the validation problem; never auto-rewrite or generate a replacement title
- Thumbnail fail -> Thumbnail_Agent
- Script fail -> Script_Agent
- Medical Gate 2 fail -> Script_Agent or Research_Agent
- Production fail -> Production_Agent
- SEO fail -> SEO_Agent
- Final QA fail -> return to the specific failed agent
- Project Summary fail -> Orchestrator

---

## 5. Gate Policy

Any block-severity failure halts the pipeline. Medical gates are non-negotiable. Final QA is the last publishing gate and must verify all project files, packaging match, medical safety, production readiness, SEO safety, and summary readiness.

---

*End of document.*
