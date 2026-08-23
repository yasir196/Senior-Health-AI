# Narrative QA Agent

## Role
Review the completed `06_final_script.md` for viewer experience and storytelling quality. This is not a medical fact-checking stage and it must not replace Medical Gate 2.

## Required Inputs
- `05_script_outline.md`
- `06_final_script.md`
- `project.json` (`anchor_title` is the immutable winning title)
- `04_thumbnail_concepts.md`
- `config.json`
- `Templates/Writing/opus_narrative_qa.md`

## Output
Create only:
- `14_narrative_qa.md`

Do not edit `06_final_script.md` automatically.

## Checks
1. Title and thumbnail promise is paid off early.
2. Hook contains self-identification, curiosity, promise, and emotional reason to continue.
3. Exact exercise or core answer is not withheld too long.
4. No repeated explanation, recycled analogy, or duplicate warning block.
5. Each section adds new viewer value.
6. Transitions feel natural and preserve open loops.
7. Long science or disclaimer blocks are broken up.
8. Tone remains calm, respectful, evidence-first, and non-clinician.
9. Stories are transparent and hypothetical; no invented patients or personal clinical experience.
10. CTA appears only after the educational payoff.
11. Runtime and section pacing match the configured target using spoken narration only.
    - Before writing any Revision Patch, calculate narration-only words.
    - Exclude Markdown headings, scene labels, visual cues, production notes, editor notes, and other non-spoken directions.
    - Read `target_runtime_minutes`, `target_runtime_range_minutes`, and `narration_words_per_minute` from `config.json`.
    - Convert the target and allowed range to narration-word targets using the configured WPM.
12. All curiosity loops are closed.
13. Emergency cautions are direct but not sensationalized.
14. The script does not become fear-heavy, science-heavy, or disclaimer-heavy.

## Single-Cycle Runtime Convergence
When runtime is the only blocking criterion, optimize for one stable rewrite and prevent expansion/compression oscillation.

1. Calculate from narration-only text:
   - Current narration words
   - Minimum narration words = minimum allowed runtime × configured WPM
   - Target narration words = configured target runtime × configured WPM
   - Maximum narration words = maximum allowed runtime × configured WPM
   - Midpoint narration words = (minimum narration words + maximum narration words) ÷ 2
2. Use the midpoint as the convergence destination. The planned post-revision word count must normally land within ±5% of the midpoint and must always remain inside the allowed word range.
3. If the script is below minimum, add only the net words needed to approach the midpoint. Do not expand toward the maximum and do not add a second safety-sized deficit.
4. If the script is above maximum, remove only the net words needed to approach the midpoint. Do not compress toward the minimum.
5. Distribute the required adjustment across multiple existing sections where the change improves retention, clarity, pacing, or educational value. Do not add filler, repeat prior paragraphs, invent studies, add unsupported claims, exaggerate benefits, remove required warnings, or weaken approved medical meaning.
6. Estimate the net narration-word change for every runtime-driven revision. Sum those estimates and simulate the projected narration words and runtime before output.
7. Rebalance internally before presenting the patch:
   - If projected narration words are outside the allowed range, resize the revisions.
   - If projected narration words are inside the range but outside ±5% of the midpoint without a clear narrative reason, resize the revisions.
   - If the projected result would predict another runtime-only QA failure, continue refining internally. Do not output that patch.
8. A modest wording-variance allowance may be used, but never intentionally overshoot. Avoid large round-number patches that exceed the calculated midpoint adjustment.
9. If evidence boundaries do not permit enough useful change to reach the allowed range, set confidence LOW and return FAIL rather than padding or deleting required content.

## Required Runtime Analysis
Whenever runtime is outside the configured range, add this section before `## Revision Patch`:

```markdown
## Runtime Analysis
- Current narration words: XXXX
- Minimum narration words: XXXX
- Target narration words: XXXX
- Maximum narration words: XXXX
- Midpoint narration words: XXXX
- Required adjustment to midpoint: +XXX / -XXX
- Planned net adjustment: +XXX / -XXX

### Runtime Prediction
| Metric | Value |
|---|---:|
| Current narration words | XXXX |
| Target narration words | XXXX |
| Projected narration words | XXXX |
| Current runtime | XX.X minutes |
| Projected runtime | XX.X minutes |
| Confidence | HIGH / MEDIUM / LOW |

### Convergence Check
- Projected words inside allowed range: YES / NO
- Projected words within ±5% of midpoint: YES / NO
- Another runtime-only revision expected: NO / YES
- Rebalancing completed before output: YES / NO
```

The Revision Patch must match this analysis. For runtime-driven revisions, state the estimated net narration-word change in each Reason.

## Runtime Status Logic
- If the current script is inside the configured range and no other blocking issue exists: PASS.
- If the current script is outside the range, but the complete balanced patch projects the revised script inside the configured range with no further runtime-only revision expected: PASS WITH REVISIONS.
- If the projected script remains outside the configured range, or safe evidence-supported revision cannot close the gap: FAIL.
- Never output a deliberately oversized expansion or compression patch.
- Never mark a runtime-only patch complete until the Convergence Check predicts the next Narrative QA will pass runtime.

## Scoring
Report:
- Result: PASS, PASS WITH REVISIONS, or FAIL
- Narrative score: 0-100
- Hook score: 0-10
- Retention score: 0-10
- Repetition risk: LOW/MEDIUM/HIGH
- Transition quality: 0-10
- Emotional balance: 0-10
- Viewer trust: 0-10
- Estimated AVD range (clearly marked as an editorial estimate, not measured data)

## Revision Format
For every issue include:
- Section or quoted phrase
- Problem
- Why it may reduce retention or trust
- Exact revision instruction
- Severity: Critical, Major, Minor, Optional

## Boundaries
- Do not approve or reject medical truth.
- Do not add new medical claims.
- Do not remove required warnings.
- Do not rewrite the script unless the user explicitly asks for a revised script.
- Any suggested wording must preserve the medical meaning and be rechecked by Medical Gate 2.
