# 14 - Channel SOP

> Permanent internal documentation. Senior Health YouTube Production System.
> Complete operating manual for producing one video, start to finish.

---

## 1. One Video, Start To Finish

1. **Topic input:** Receive the exact topic and create a safe topic slug.
2. **Opportunity validation:** Run Outlier_Agent. Save `01_topic_validation.md`.
3. **Research:** Run Research_Agent from the approved opportunity. Save `02_research_sheet.md`.
4. **Medical Gate 1:** Run Medical_Agent on the research sheet. If it fails, return to Research_Agent.
5. **Winning title and thumbnail:** The user-supplied `project.json.anchor_title` is already the winning title. Do not run title generation. Run Thumbnail_Agent after Medical Gate 1 and save `04_thumbnail_concepts.md` and `11_thumbnail_prompt.md`.
6. **Script:** Run Script_Agent using topic validation, research, titles, and thumbnail concepts. Save `05_script_outline.md` and `06_final_script.md`.
7. **Medical Gate 2:** Run Medical_Agent on the final script. If wording fails, return to Script_Agent. If evidence fails, return to Research_Agent.
8. **Production:** Run Production_Agent after Medical Gate 2 passes. Save `07_production_sheet.csv`, `10_image_prompts.md`, and `12_broll_prompts.md`.
9. **SEO:** Run SEO_Agent using titles, research, script, and production sheet. Save `08_youtube_metadata.md`.
10. **Final QA:** Verify every required file, every gate, packaging match, medical safety, production readiness, SEO safety, and publish/schedule readiness. Save `09_qa_checklist.md`.
11. **Publish/Schedule checklist:** Record the publish/schedule go/no-go inside the QA checklist.
12. **Project Summary:** Save `14_project_summary.md` as the final handoff summary for the completed production package.

---

## 2. Required Project Files

Every project must live in `Projects/<topic_slug>/` and include:

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

## 3. Gate Summary

| Gate | Stage | Pass Condition | On Fail |
|---|---|---|---|
| Opportunity | After topic input | Topic has strategic fit and output file exists | Return to Outlier_Agent |
| Research | After opportunity | Evidence and contraindications documented | Return to Research_Agent |
| Medical Gate 1 | After research | Zero block-severity medical violations | Return to Research_Agent |
| Winning Title | Project creation + validation | User-supplied title validated; never regenerated | Stop/report if title promise is unsupported |
| Thumbnail | After Medical Gate 1 | Safe concepts and final thumbnail prompt pass | Return to Thumbnail_Agent |
| Script | After title and thumbnail | State machine, hook, loops, caveat pass | Return to Script_Agent |
| Medical Gate 2 | After script | Script claims match evidence | Return to Script_Agent or Research_Agent |
| Production | After Medical Gate 2 | Timed scenes, avatar/B-roll modes, image prompts, and B-roll prompts complete | Return to Production_Agent |
| SEO | After production | Metadata matches content and caveat present | Return to SEO_Agent |
| Final QA | Before publish/schedule | All required files and gates pass | Return to specific failed agent |

---

## 4. Governing Principles

1. Format discipline over improvisation.
2. Whitespace over imitation.
3. Rotate emotional anchors across the calendar.
4. Accuracy is non-negotiable and treated as a growth asset.
5. Packaging must always match content.
6. The output of each agent becomes the input for the next agent.
7. Publish or schedule only after Final QA passes.

---

## 5. Project Summary Responsibilities

`14_project_summary.md` must be created after Final QA and the publish/schedule checklist. It must summarize the topic, approved angle, selected title, thumbnail direction, script duration target, medical gate status, production deliverables, publish readiness, and any unresolved blockers. It must not introduce new claims, new medical advice, or new creative directions that are not already present in the approved project files.

---

*End of document.*
