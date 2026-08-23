# 15 - Master Checklists

> Permanent internal documentation. Senior Health YouTube Production System.
> These checklists are the operational gates for every video.

---

## 1. Opportunity Checklist

- [ ] Topic input recorded
- [ ] Topic slug created
- [ ] Opportunity score calculated
- [ ] Proven format selected
- [ ] Emotional anchor selected
- [ ] Withheld payoff identified
- [ ] One hero object identified
- [ ] `01_topic_validation.md` saved in `Projects/<topic_slug>/`

---

## 2. Research Checklist

- [ ] Core claim defined
- [ ] Evidence Library checked for matching approved sources and claims
- [ ] Strongest citation recorded (Tier 1-4)
- [ ] At least three trustworthy references included when available
- [ ] Mechanism explained in plain language
- [ ] Contraindications documented
- [ ] Unsupported elements removed
- [ ] `02_research_sheet.md` saved in `Projects/<topic_slug>/`

---

## 3. Medical Gate 1 Checklist

- [ ] Every claim traces to Tier 1-4 evidence
- [ ] No individual diagnosis
- [ ] No cure promise
- [ ] No medication-stopping or medication-altering instruction
- [ ] Clinician caveat present when needed
- [ ] Statistics accurate and in context
- [ ] Evidence Library source IDs and claim IDs verified when reused
- [ ] `13_fact_check_log.md` created or updated with Gate 1 result
- [ ] Result routes to Research_Agent on fail

---

## 4. Title Checklist

- [ ] Title set uses approved claim boundaries
- [ ] Self-identification present
- [ ] Curiosity gap present
- [ ] Viewer benefit present
- [ ] Recommended title selected
- [ ] No medical overclaim
- [ ] `project.json.anchor_title` exists and is the exact user-supplied winning title

---

## 5. Thumbnail Checklist

- [ ] One dominant word readable at 120px
- [ ] Exactly one recognizable hero object per concept
- [ ] Clear facial emotion, never neutral
- [ ] Dark background with yellow/red text
- [ ] One directional cue
- [ ] No fake medical result visuals
- [ ] `04_thumbnail_concepts.md` saved in `Projects/<topic_slug>/`
- [ ] `11_thumbnail_prompt.md` saved in `Projects/<topic_slug>/`

---

## 6. Script Checklist

- [ ] Hook follows five-beat structure
- [ ] Loop maintained every 60-90 seconds
- [ ] Items revealed in ascending importance
- [ ] Strongest payoff restated near the end
- [ ] At least one clear actionable takeaway
- [ ] Payoff matches title and thumbnail
- [ ] Clinician caveat included
- [ ] `05_script_outline.md` and `06_final_script.md` saved in `Projects/<topic_slug>/`

---

## 7. Medical Gate 2 Checklist

- [ ] Final script claims match research sheet
- [ ] No unsupported stronger wording
- [ ] No medication alteration instruction
- [ ] No cure or reversal promise
- [ ] Caveat present in script
- [ ] `13_fact_check_log.md` updated with Gate 2 result
- [ ] Failure routes to Script_Agent or Research_Agent

---

## 8. Production Checklist

- [ ] `07_production_sheet.csv` includes scene timing
- [ ] Avatar/B-roll mode included for every scene
- [ ] Visual prompts included for every scene
- [ ] Images match narration
- [ ] Captions and audio synchronization planned
- [ ] Medical caveats appear visually when relevant
- [ ] `10_image_prompts.md` saved in `Projects/<topic_slug>/`
- [ ] `12_broll_prompts.md` saved in `Projects/<topic_slug>/`

---

## 9. SEO Checklist

- [ ] `08_youtube_metadata.md` saved in `Projects/<topic_slug>/`
- [ ] Metadata matches title, thumbnail, and script
- [ ] Description caveat present
- [ ] Sources listed
- [ ] Tags relevant and not stuffed
- [ ] Pinned comment includes caveat when needed

---

## 10. Final QA Checklist

- [ ] All required files `01` through `14` are present
- [ ] All medical gates passed
- [ ] Retention structure intact
- [ ] Packaging matches content
- [ ] Brand voice consistent
- [ ] Legal and policy compliance confirmed
- [ ] Publish/schedule checklist complete or blocked with reason
- [ ] Failure routes to the specific failed agent

---

## 11. Publish/Schedule Checklist

- [ ] Recommended title selected
- [ ] Thumbnail final and legible in feed
- [ ] Metadata ready
- [ ] Description caveat present
- [ ] Schedule window selected or intentionally left pending
- [ ] No failed validation gates remain

---

## 12. Project Summary Checklist

- [ ] `14_project_summary.md` saved in `Projects/<topic_slug>/`
- [ ] Topic and approved angle summarized
- [ ] Selected title and thumbnail direction listed
- [ ] Script duration target and final status recorded
- [ ] Medical Gate 1 and Gate 2 results summarized from `13_fact_check_log.md`
- [ ] Production deliverables listed: `07_production_sheet.csv`, `10_image_prompts.md`, and `12_broll_prompts.md`
- [ ] Publish/schedule readiness summarized
- [ ] No new unsupported claims or new creative directions introduced

---

## 13. Gate Severity Model

| Severity | Action |
|---|---|
| Block | Halt the pipeline and return to the named failed agent |
| Warn | Log and proceed only if no block rule is violated |

---

*End of document.*
