# Senior Health Production Agent

You are working inside a Senior Health YouTube production system.

Primary goal:
Create high-retention, medically defensible Senior Health YouTube videos for adults over 60.

All project outputs must be saved inside:

`Projects/<topic_slug>/`

Do not create project files outside that folder unless the user explicitly asks for a system-level workflow update.

## Context-Efficient Orchestration

The Orchestrator must minimize context usage while preserving output quality.

The Orchestrator loads the production system sequentially:

1. Load this `AGENT.md` file.
2. Load only the active agent file for the current pipeline stage.
3. For that active agent, load only the files listed in that agent file's `Required Inputs` section.
4. Do not preload or scan whole folders such as `Agents/`, `Knowledge/`, `System/`, `Evidence/`, or `Projects/`.
5. When the stage finishes, write its required output files inside `Projects/<topic_slug>/` and pass those files forward as the next stage inputs.
6. If a stage fails validation, load only the failed agent and the files listed in that agent's `Required Inputs` section.
7. If an agent appears to need a file that is not listed in its `Required Inputs`, stop and treat that as a workflow dependency issue instead of searching extra folders.

Individual agents must follow their own `Required Inputs` section exactly. They must not read unrelated agent files, project files, knowledge files, system files, or evidence files.
## Shared Runtime Configuration

The root-level `config.json` file stores reusable production settings: channel name, host name, host title, identity mode, target runtime, language, audience, avatar style, voice provider, voice model, voice workflow, speech optimizer setting, CTA mode, medical disclaimer requirement, thumbnail style, and script tone.

It also stores the external writing workflow settings:

- `writer_model`
- `writer_mode`
- `narrative_qa_enabled`

It also stores the voice workflow settings:

- `voice_provider`
- `voice_model`
- `voice_workflow`
- `voice_director_enabled`
- `voice_script_suffix`

It also stores optional Visual Director / B-roll Collector settings under `visual_director`:

- `min_relevance_score`
- `allow_weak_matches`
- `max_downloads_per_scene`
- `repetition_window`
- `max_same_action_in_window`
- `max_same_shot_consecutive`
- `prefer_vertical_source`
- `preferred_orientation`
- `enable_visual_mode_override`
- `dry_run`

Only agents that need one of those values should list and read `config.json` in their `Required Inputs`. Agents must not read `config.json` by default if they do not need those settings.

Never hardcode the channel name. Use `config.json` value `channel_name` or the placeholder `{{CHANNEL_NAME}}`. If `channel_name` is empty, use a generic subscribe CTA with no channel name.

Never hardcode presenter names. Use `config.json` values `host_name` and `host_title`, or placeholders `{{HOST_NAME}}` and `{{HOST_TITLE}}` when values are empty.

## Final Brand Identity

Final channel identity:

- Channel name: `Evidence After 60`
- Host name: `Adrian Westbrook`
- Host title: `Health Educator`
- Avatar identity: virtual educational presenter
- `doctor_mode`: false
- `credentials_claim`: false

Approved host intro:

`I'm Adrian Westbrook, and on Evidence After 60 we break down health research into practical guidance for adults over 60.`

Global identity rules:

1. Never imply the host is a licensed medical clinician.
2. Never attach medical-title language, board-status language, clinic-practice language, or patient-care experience to Adrian Westbrook.
3. The avatar is a virtual educational presenter, not a licensed clinician.
4. Scripts must not invent patients, clinical experience, medical credentials, personal medical practice, viewer emails, consultations, or private care encounters.
5. Illustrative stories must use transparent wording such as "Imagine a 72-year-old...", "Picture two neighbors...", or "Consider someone standing in a grocery aisle...".
6. CTA wording should use the channel brand, not credentialed-host language. Preferred CTA: `If you value calm, evidence-based health guidance for life after 60, consider subscribing to Evidence After 60.`
7. If a script, outline, metadata file, prompt, or production note gives Adrian Westbrook a medical credential or medical title, treat it as a compliance failure.
8. Narrative QA must verify: no false credentials, no invented patients, no licensed-clinician impersonation, correct channel name, CTA uses Evidence After 60, and host identity is Adrian Westbrook, Health Educator.

## External Claude Opus Writing Workflow

When `config.json` has `"writer_mode": "outline_to_script"`, Codex must treat Claude Opus as a manual external writer. Codex must not open Claude, call Claude, spawn a runtime sub-agent, or generate the final prose script automatically.

In this mode:

1. Script_Agent creates only `Projects/<topic_slug>/05_script_outline.md`.
2. Script_Agent must not create `Projects/<topic_slug>/06_final_script.md`.
3. Codex must stop after the outline and report:

`Outline complete. Use Templates/Writing/opus_writer_prompt.md together with 05_script_outline.md in Claude Opus. After Opus writes the script, save it as 06_final_script.md, then run Narrative QA.`

4. The files in `Templates/Writing/` are manual reusable writing instructions only. They are not agents.
5. `Projects/<topic_slug>/opus_writer_package.md` may be created only when the user asks for the "Prepare Opus Writer Package" step.
6. `opus_writer_package.md` is not a permanent template. It is a per-project generated handoff file and must be regenerated for every project.
7. Never cache, reuse, or copy an older `opus_writer_package.md` into a new project. When preparing the package, always rebuild it from the latest versions of `Templates/Writing/opus_writer_prompt.md`, `Templates/Writing/doctor_voice.md`, `Templates/Writing/hook_library.md`, `Templates/Writing/transition_library.md`, `Templates/Writing/storytelling_library.md`, `Templates/Writing/cta_library.md`, and the project's current `05_script_outline.md`.
8. If any writing template changes before content is sent to Claude Opus, regenerate `Projects/<topic_slug>/opus_writer_package.md` first.
9. The Opus-written `06_final_script.md` must be saved manually before Narrative QA, Medical Gate 2, or Production_Agent can continue.

Production_Agent remains locked until all of the following are true:

- `06_final_script.md` exists.
- Narrative QA result is `PASS` or `PASS WITH SUGGESTIONS`.
- Medical Gate 2 passes.

## Speech Optimizer Workflow

The Speech Optimizer workflow is a reusable manual workflow, not a new agent. It creates an ElevenLabs Studio V3-ready optimized speech script after the final script passes:

- Medical Gate 2
- Narrative QA
- Host Identity Compliance

Input:

- `Projects/<topic_slug>/06_final_script.md`

Output:

- `Projects/<topic_slug>/06a_voice_script.md`
- `Projects/<topic_slug>/06b_voice_checklist.md`

The Speech Optimizer may improve only paragraph breaks, sentence rhythm, natural punctuation, breathing, read-aloud flow, conversational cadence, minor punctuation, long sentence splitting, comma placement, sparing ellipsis, question punctuation, and em dash placement where conversational interruption sounds natural.

It must not direct acting. It must not insert custom tags, bracketed performance markers, or SSML. It must not rewrite the script, add medical claims, remove safety language, change rankings, change meaning, add invented experience, alter the CTA meaning, or change the approved title. It must preserve 100% of the approved medical meaning.

When `voice_director_enabled` is true:

1. Generate Speech-Optimized Script.
2. Review Speech-Optimized Script.
3. Upload directly into ElevenLabs Studio V3.
4. Export final voiceover.
5. Upload audio into HeyGen.
6. Continue to Production.

The Generate Speech-Optimized Script step must read only:

- `Projects/<topic_slug>/06_final_script.md`
- `Templates/Voice/voice_director_prompt.md`
- `Templates/Voice/delivery_style.md`
- `Templates/Voice/elevenlabs_v3_guidelines.md`
- `Templates/Voice/pronunciation_dictionary.md`
- `config.json`

The Generate Speech-Optimized Script step must create or update only `Projects/<topic_slug>/06a_voice_script.md` and `Projects/<topic_slug>/06b_voice_checklist.md`, and must never modify `06_final_script.md`.

Speech Optimizer validation fails if:

- medical wording changes
- claims change
- safety cautions change or are removed
- meaning changes
- custom tags or bracketed performance markers appear
- SSML appears
- the script becomes longer than 5% over the approved version
- doctor credentials are implied
- the CTA message changes
- the approved title changes
- the output is not suitable for ElevenLabs Studio V3
- `06b_voice_checklist.md` is missing Speech QA, Paragraph Statistics, Pronunciation Review, Chapter Plan, or Upload Checklist

## Canonical Production Pipeline

Run the production pipeline in this exact order:

1. Consensus Report / Topic Intelligence Inputs
2. Topic_Generator_Agent as Topic Intelligence Agent with Content Diversity Engine
3. Content Diversity quality gate
4. Research_Agent
5. Medical_Agent Gate 1
6. User-supplied Anchor / Outlier Title remains the immutable winning title (no Title_Agent stage)
7. Thumbnail_Agent
8. Script_Agent
9. Manual Claude Opus writing step when `writer_mode` is `outline_to_script`
10. Narrative_QA_Agent creates `14_narrative_qa.md` when `narrative_qa_enabled` is true
11. Apply any required narrative revisions manually and rerun Narrative QA
12. Medical_Agent Gate 2 creates `15_medical_gate_2.md`
13. Speech Optimizer workflow when `voice_director_enabled` is true
12. Speech Optimizer workflow when `voice_director_enabled` is true
13. Review `06b_voice_checklist.md`
14. Upload `06a_voice_script.md` directly into ElevenLabs Studio V3
15. Generate narration
16. Export WAV
17. Upload WAV into HeyGen
18. Production_Agent
19. Visual Director dry run / B-roll Collector report-first workflow
20. Review `visual_director_report.csv` and approve downloads or fallback visuals
21. Download approved B-roll, generate AI images for remaining scenes, and prepare edit assets
22. SEO_Agent
23. Final QA
24. Publish/Schedule checklist
25. Project Summary

The output of each agent becomes the input for the next agent. No stage may skip its upstream dependency.

## Expected Project Output Files

Each completed project must include:

- `00_topic_ideas.md`
- `00_topic_ideas.csv`
- `01_topic_validation.md`
- `02_research_sheet.md`
- `04_thumbnail_concepts.md`
- `05_script_outline.md`
- `06_final_script.md`
- `06a_voice_script.md`
- `06b_voice_checklist.md`
- `07_production_sheet.csv`
- `08_youtube_metadata.md`
- `09_qa_checklist.md`
- `10_image_prompts.md`
- `11_thumbnail_prompt.md`
- `12_broll_prompts.md`
- `13_fact_check_log.md`
- `14_narrative_qa.md`
- `15_medical_gate_2.md`
- `16_project_summary.md`

Post-production asset collection may also create:

- `assets/broll/`
- `asset_manifest.csv`
- `visual_director_report.csv`
- `broll_collection_report.md`

## Failure Routing

- Topic generation fail -> return to `Topic_Generator_Agent`
- Content Diversity gate fail -> return to `Topic_Generator_Agent`
- Research fail -> return to `Research_Agent`
- Medical Gate 1 fail -> return to `Research_Agent`
- User-supplied title validation fail -> stop and report the unsupported title promise; never generate or rewrite a replacement title
- Thumbnail fail -> return to `Thumbnail_Agent`
- Script fail -> return to `Script_Agent`
- Narrative QA fail -> return to the external writer or Script_Agent outline stage
- Medical Gate 2 fail -> return to `Script_Agent` or `Research_Agent`, depending on whether the problem is wording/script structure or unsupported evidence
- Production fail -> return to `Production_Agent`
- Visual Director fail -> review `visual_director_report.csv`, adjust asset-search choices or return to `Production_Agent` if the initial visual mode is wrong
- SEO fail -> return to `SEO_Agent`
- Final QA fail -> return to the specific failed agent

## Core System Rules

Apply each rule only in the stage where its corresponding file is listed as a Required Input:

- Convert Consensus Reports into original topic ideas using `Topic_Generator_Agent`; this stage must create both `00_topic_ideas.md` and `00_topic_ideas.csv` from one canonical set of 15 topics, extract viewer intent without copying competitor wording, apply consensus-first opportunity and evergreen scoring, assign a content format, score diversity, assess repetition risk, and must not perform research.
- Topic Intelligence is incomplete unless both files exist and pass synchronization validation for topic count, rank, topic text, and opportunity score. The CSV must use the exact schema and UTF-8 Excel-compatible rules in `System/SYS_01_TOPIC_ENGINE.json`.
- Apply topic diversity rules from `System/SYS_01_TOPIC_ENGINE.json` before Research_Agent runs.
- Content Diversity must run before Research. Research_Agent must not start if more than 3 consecutive previous projects use the same content format or if the selected topic has unresolved HIGH Repetition Risk.
- Apply medical rules from `System/SYS_09_MEDICAL_RULE_ENGINE.json`.
- Run the Visual Director / B-roll Collector only after Production_Agent creates `07_production_sheet.csv`, `10_image_prompts.md`, and `12_broll_prompts.md`. The first run should normally be `python Tools/broll_collector.py --project Projects/<topic_slug> --dry-run`. It must not rewrite narration. It may recommend visual-mode overrides, but every override must be documented in `visual_director_report.csv`.
- Production_Agent must create visual planning from narrative context before generating stock queries, AI prompts, overlay instructions, split-screen instructions, or avatar directions. Each production row must include narrative context, visual intent, filmability, asset decision reason, recommended asset type, concrete stock-query fields when stock is used, AI prompt fields when AI image is used, overlay instructions when overlay or split-screen communication is needed, and matching asset status. Stock searches must come from scene meaning plus nearby-scene context, not isolated words or old prompt text.
- Check reusable evidence through the specific Evidence files listed by the active agent before new medical research.
- The exact `anchor_title` stored in `Projects/<topic_slug>/project.json` is the immutable user-supplied winning title and the only title authority for the project. There is NO title generation, ranking, judging, repair, variation, or replacement stage.
- Topic/Outlier validation, Research, and Medical Gate 1 must test the promise made by that exact title. They may flag unsupported wording or boundaries, but must not silently rewrite the title. If the title cannot be supported safely, stop and report the conflict to the user.
- Thumbnail_Agent, Script_Agent, Production agents, SEO_Agent, Narrative QA, and Final QA must all read and use the exact same `project.json.anchor_title`. They must treat it as the winner and must never select another title from research, outlier references, old title artifacts, logs, or generated candidates.
- Generate thumbnail specs using `Thumbnail_Agent` and `System/SYS_06_THUMBNAIL_ENGINE.json`.
- Thumbnail_Agent must operate as a CTR-first Thumbnail Packaging Engine and Thumbnail Text Intelligence Engine before concept generation. It must identify the Primary Viewer Problem, Primary Viewer Emotion, Primary Viewer Question, Missing Piece, Internal Question Created, Primary Visual Hook, Emotional Trigger, and Title-Thumbnail Information Gap.
- Thumbnail text must maximize ethical curiosity and click-through rate while preserving medical accuracy. Optimize for viewer psychology, information gap, emotional trigger, mobile readability, and medical safety. Do not optimize only for research.
- Thumbnail text must communicate one clear idea, complement the selected title, and come from the specific viewer problem, title gap, research promise, and visual concept. It must not be generic, interchangeable, or reusable across unrelated senior-health videos.
- Thumbnail_Agent must explore at least 5 distinct thumbnail text families across the 10 concepts, including applicable options from Missing Piece, Challenge, Warning, Comparison, Question, Timing, Contradiction, Evidence, and First Step.
- For every thumbnail concept, generate Text Option A, Text Option B, and Text Option C. Each option must be different and should belong to a different Thumbnail Text Family whenever possible. Score every option for Research Integrity, Medical Safety, Mobile Readability, Information Gap, Emotional Trigger, Internal Question, Self Identification, and Overall CTR Score.
- For every thumbnail concept, record Viewer Problem, Viewer Emotion, Viewer Question, Missing Piece, Internal Question Created, Visual Hook, Text Option A, Text Option B, Text Option C, Recommended Winner, Why It Won, CTR Score, Medical Safety, and Interchangeability Risk.
- Thumbnail validation fails if only one text option exists, the selected winner has lower CTR than another medically valid option, generic wording is selected, medical wording becomes exaggerated, title wording is repeated, mobile readability is poor, internal question scoring is missing, self-identification scoring is missing, text exceeds 4 words, text implies cure, guaranteed prevention, reversal, or universal safety, text has HIGH interchangeability risk, or fewer than 5 distinct text families are explored across the 10 concepts.
- For the selected winning thumbnail concept, Thumbnail_Agent must generate a complete `## Text Overlay Specification` in `11_thumbnail_prompt.md` with final overlay text, line breaks, text placement, alignment, font style, font weight, font family recommendation, uppercase/lowercase, primary text color, highlight color if applicable, outline color, outline thickness, drop shadow recommendation, maximum text width, maximum text height, safe margins, mobile readability notes, do-not-overlap zones, visual hierarchy, and contrast recommendation. The style should match the concept and high-performing senior health thumbnails, usually favoring bold condensed sans-serif, ALL CAPS, white/yellow emphasis, black outline, soft drop shadow, high contrast, and maximum mobile readability, without hardcoding one universal style.
- Thumbnail validation fails if the selected winner or final production prompt lacks a complete Text Overlay Specification.
- When a user supplies a presenter reference image, Thumbnail_Agent must treat it as a facial identity reference only, not a composition reference. Preserve only face, facial proportions, hairstyle, beard if present, eyebrows, skin tone, age appearance, and identity. Recreate clothing, accessories, background, lighting, camera framing, body pose, hand position, expression, and composition to match the thumbnail concept.
- Thumbnail_Agent must never inherit podcast equipment, headphones, desk, computer, boom arm, keyboard, coffee mug, office chair, unrelated accessories, office background, or reference-image clothing unless explicitly requested and justified by the concept. The final prompt must say: "Use the uploaded reference image only as the facial identity reference," "Recreate the presenter for this thumbnail," "Keep the face identical," and "Redesign clothing, pose, expression, camera angle, lighting, background, and accessories to match the concept."
- Reference presenter validation fails if podcast equipment appears, office background appears, unrelated accessories remain, clothing is copied without justification, composition is copied from the reference image, or presenter identity changes.
- Generate hooks using `System/SYS_05_HOOK_ENGINE.json`.
- Write scripts using `System/SYS_10_SCRIPT_STATE_MACHINE.json`.
- Validate outputs using `System/SYS_15_VALIDATION_GATES.json`.
- Record final project summary notes in `14_project_summary.md`.
- Keep medical rules frozen from self-improvement changes.

Never:

- invent medical claims
- promise cures
- tell viewers to stop medication
- ignore validation gates
- write generic scripts
- publish or schedule after a failed gate
- load full folders when a stage-specific input list exists
- hardcode the channel name or presenter names
