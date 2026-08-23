# 11 - Content Production SOP

> Permanent internal documentation. Senior Health YouTube Production System.
> This document is standalone and self-contained.

---

## 1. End-to-End Pipeline

| Order | Stage | Owner / Agent | Input | Output |
|---:|---|---|---|---|
| 1 | Topic input | User / Orchestrator | Video topic | Topic string and topic slug |
| 2 | Opportunity validation | Outlier_Agent | Topic string | `01_topic_validation.md` |
| 3 | Research | Research_Agent | `01_topic_validation.md` | `02_research_sheet.md` |
| 4 | Medical Gate 1 | Medical_Agent | `02_research_sheet.md` | `13_fact_check_log.md` gate entry |
| 5a | Winning Title | User | Project creation | `project.json.anchor_title` (immutable) |
| 5b | Thumbnail | Thumbnail_Agent | `project.json.anchor_title`, `01_topic_validation.md`, `02_research_sheet.md`, Medical Gate 1 pass | `04_thumbnail_concepts.md`, `11_thumbnail_prompt.md` |
| 6 | Script | Script_Agent | `project.json.anchor_title`, `01_topic_validation.md`, `02_research_sheet.md`, `04_thumbnail_concepts.md` | `05_script_outline.md`, `06_final_script.md` |
| 7 | Medical Gate 2 | Medical_Agent | `02_research_sheet.md`, `06_final_script.md` | updated `13_fact_check_log.md` |
| 8 | Production | Production_Agent | `06_final_script.md`, `04_thumbnail_concepts.md`, `11_thumbnail_prompt.md`, Medical Gate 2 pass | `07_production_sheet.csv`, `10_image_prompts.md`, `12_broll_prompts.md` |
| 9 | SEO | SEO_Agent | `project.json.anchor_title`, `02_research_sheet.md`, `06_final_script.md`, `07_production_sheet.csv` | `08_youtube_metadata.md` |
| 10 | Final QA | Orchestrator | All project outputs | `09_qa_checklist.md` |
| 11 | Publish/Schedule checklist | Orchestrator | `09_qa_checklist.md`, `08_youtube_metadata.md` | Publish/schedule status inside QA checklist |
| 12 | Project Summary | Orchestrator | All completed project outputs | `14_project_summary.md` |

---

## 2. Stage Rules

1. All outputs must be saved inside `Projects/<topic_slug>/`.
2. The output of each agent becomes the input for the next agent.
3. Medical_Agent must create and maintain `13_fact_check_log.md` across Gate 1 and Gate 2.
4. No Title_Agent runs. Thumbnail_Agent runs after Medical Gate 1 and uses `project.json.anchor_title` as the immutable winning title.
5. Script_Agent cannot run until `project.json.anchor_title` and `04_thumbnail_concepts.md` exist.
6. Production_Agent cannot run until Medical Gate 2 passes.
7. SEO_Agent cannot run until `07_production_sheet.csv` exists.
8. Final QA must check all required project files from `01_topic_validation.md` through `14_project_summary.md`.
9. No video publishes or schedules after a failed gate.

---

## 3. Failure Routing

| Failure | Return To |
|---|---|
| Research fail | Research_Agent |
| Medical Gate 1 fail | Research_Agent |
| User-supplied title validation fail | Stop and report unsupported promise; never auto-generate a replacement |
| Thumbnail fail | Thumbnail_Agent |
| Script fail | Script_Agent |
| Medical Gate 2 fail | Script_Agent or Research_Agent |
| Production fail | Production_Agent |
| SEO fail | SEO_Agent |
| Final QA fail | Specific failed agent |
| Project Summary fail | Orchestrator |

---

## 4. Required Project Files

Every completed project must contain:

- `01_topic_validation.md`
- `02_research_sheet.md`
- `project.json` (`anchor_title` = immutable winning title)
- `04_thumbnail_concepts.md`
- `05_script_outline.md`
- `06_final_script.md`
- `07_production_sheet.csv`
- `08_youtube_metadata.md`
- `09_qa_checklist.md`
- `10_image_prompts.md`
- `11_thumbnail_prompt.md`
- `12_broll_prompts.md`
- `13_fact_check_log.md`
- `14_project_summary.md`

---

## 5. QA & Publishing

Final QA is a hard gate. It must confirm medical safety, packaging match, retention structure, production readiness, SEO safety, publish/schedule readiness, and all required files. Publish or schedule only after Final QA passes.

---

## 6. Project Summary

`14_project_summary.md` is the final handoff file. It summarizes the topic, approved title, medical caveats, package status, open publishing items, and next recommended action. It must not introduce new claims or override medical gates.

---

*End of document.*
