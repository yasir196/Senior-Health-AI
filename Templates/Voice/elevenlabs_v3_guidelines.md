# ElevenLabs Studio V3 Guidelines

Optimize specifically for ElevenLabs Studio V3. Always use Studio V3 for this workflow.

## Studio V3 Workflow

- Upload one complete narration file.
- Use one consistent voice.
- Keep one consistent style setting.
- Keep one consistent stability setting.
- Avoid regenerating random paragraphs.
- Maintain punctuation because Studio uses punctuation for pacing.
- Review pronunciation before export.
- Regenerate only the affected chapter if pronunciation needs correction.
- Export one complete narration.
- Use WAV when practical.

## Script Preparation

The Studio V3 input should be clean narration text with natural paragraph breaks and punctuation.

Do not include:

- bracketed performance markers
- custom tags
- SSML
- production notes
- visual cues meant for editors
- QA reports unless the user explicitly wants them read aloud

## Pronunciation Review

Review difficult medical pronunciations before export, including:

- medication names
- medical abbreviations
- supplement names
- scientific terms

Use pronunciation dictionary entries where needed.

Use `Templates/Voice/pronunciation_dictionary.md` as the reusable starting point, and add project-specific pronunciation notes to `06b_voice_checklist.md`.

## Consistency Check

Before final export, listen for sudden changes in:

- energy
- speed
- pitch
- loudness
- pronunciation
- paragraph-to-paragraph style

If a section must be regenerated, use the same voice, style, stability, and loudness settings.

Prefer regenerating only the affected chapter, not random paragraphs across the project.

## HeyGen Fit

Keep pacing natural for HeyGen lip sync. Avoid overly long paragraphs, unnatural pauses, and punctuation clutter that could create uneven mouth movement.
