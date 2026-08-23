# Speech Optimizer Prompt

You are preparing an ElevenLabs Studio V3-ready speech-optimized version of an approved Evidence After 60 final script.

This is not acting direction. This is not a rewrite. This is speech optimization for Studio V3 only.

## Required Input

Use only:

- `Projects/<topic_slug>/06_final_script.md`
- `Templates/Voice/delivery_style.md`
- `Templates/Voice/elevenlabs_v3_guidelines.md`
- `Templates/Voice/pronunciation_dictionary.md`
- `config.json`

## Required Output

Create:

- `Projects/<topic_slug>/06a_voice_script.md`
- `Projects/<topic_slug>/06b_voice_checklist.md`

Never modify `06_final_script.md`.

`06a_voice_script.md` must contain spoken narration only.

Anything that would not naturally be spoken aloud by a human narrator must be removed automatically.

Automatically remove:

- video title
- section headings
- chapter headings
- the standalone line "Pause."
- internal production notes
- production notes
- production instructions
- visual cues
- Visual Cue blocks
- camera directions
- internal editing notes
- editing notes
- QA notes
- narration labels
- Markdown headings such as `#`, `##`, and `###`
- bullet points used only for structure
- numbering that is not intended to be spoken
- review reports
- runtime metrics
- retention reports
- config notes
- humanization reports

The first spoken line must always be the script hook.

Do not modify the wording of the hook itself.

Never begin `06a_voice_script.md` with the video title, "Welcome back", "Hello everyone", a channel introduction, a presenter introduction, or a subscribe request.

If the presenter introduces themselves, keep that introduction only where it naturally appears in the approved script. Do not move it to the beginning.

Preserve the approved outro and CTA. Do not remove spoken disclaimers.

Before saving `06a_voice_script.md`, perform a final cleanup pass. The final file must read exactly like a script that a human narrator would speak. If any text would sound unnatural when read aloud, remove it unless it is part of the approved narration.

The final file should require zero manual editing before upload to ElevenLabs Studio V3.

## 06b Voice Checklist

Generate `06b_voice_checklist.md` automatically after creating `06a_voice_script.md`.

It must include:

- Speech QA
- Paragraph Statistics
- Pronunciation Review
- Chapter Plan
- Upload Checklist

Speech QA must verify:

- starts with hook
- no title spoken
- no markdown
- no production notes
- no visual cues
- no editor comments
- no chapter headings
- no custom tags
- no SSML
- CTA and spoken disclaimer preserved

Paragraph Statistics must include:

- total paragraphs
- average paragraph length
- longest paragraph
- estimated narration time

Pronunciation Review must list difficult words detected in the script, using `Templates/Voice/pronunciation_dictionary.md` as the reusable reference. Add script-specific difficult terms when needed.

Chapter Plan must recommend internal ElevenLabs Studio chapters only. Do not insert chapter titles into `06a_voice_script.md`.

Suggested internal chapters:

- Hook
- Opening Curiosity
- Rank #5
- Rank #4
- Rank #3
- Rank #2
- Rank #1
- Recap
- CTA

Upload Checklist must include:

- upload complete file
- Studio V3
- same voice
- same settings
- review pronunciation
- export WAV
- send WAV to HeyGen

## Objective

Optimize the approved script so it reads naturally in ElevenLabs Studio V3 while preserving 100% of the approved medical meaning.

The optimized script must preserve:

- hook
- retention structure
- stories
- medical wording
- safety cautions
- approved claims
- rankings
- CTA meaning
- viewer promise

## Never Do

Never insert bracketed performance tags such as pause, curious, serious, smile, warm, slower, emphasis, or any other custom marker.

Never use SSML.

Never rewrite medical claims.

Never add or remove evidence.

Never change rankings.

Never change CTA meaning.

Never change the approved title.

Never imply medical credentials for Adrian Westbrook.

## Allowed Speech Optimization

You may improve only:

1. Paragraph breaks
2. Sentence rhythm
3. Natural punctuation
4. Breathing
5. Read-aloud flow
6. Conversational cadence
7. Minor punctuation improvements
8. Long sentence splitting
9. Comma placement
10. Ellipsis (...) where a natural spoken pause improves delivery
11. Question punctuation where appropriate
12. Em dash (—) where conversational interruption sounds natural

## Paragraph Rules

- Maximum 2 to 4 spoken sentences per paragraph.
- Target 40 to 90 spoken words per paragraph when practical.
- Avoid giant text blocks.
- Every paragraph should be comfortable for one natural breath group.

## Sentence Rules

- Target 12 to 20 words per sentence when practical.
- Avoid 35 to 50 word sentences.
- Split long sentences naturally without changing meaning.

## Ellipsis Rules

- Use ellipsis sparingly.
- Use ellipsis only where a thoughtful pause naturally improves delivery.
- Never overuse ellipsis.

## Question Flow

Where curiosity already exists, improve punctuation, not wording.

## Validation

Fail the optimized script if:

- medical wording changes
- claims change
- safety cautions change or are removed
- meaning changes
- custom tags appear
- SSML appears
- the script becomes longer than 5% over the approved version
- doctor credentials are implied
- CTA meaning changes
- approved title changes
- output is not suitable for ElevenLabs Studio V3
- the title appears in `06a_voice_script.md`
- any Visual Cue remains
- any production note remains
- any Markdown heading remains
- the standalone line "Pause." remains
- video title, section headings, chapter headings, visual cues, camera directions, production notes, internal editing notes, QA notes, narration labels, structural bullets, structural numbering, or reports remain in `06a_voice_script.md`
- the first spoken line is not the script hook
- the hook wording is changed
