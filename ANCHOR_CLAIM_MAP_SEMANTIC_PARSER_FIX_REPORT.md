# Anchor Claim Map Semantic Parser Fix

## Scope
Fixed only the generic Anchor → Claim Map semantic parser exposed by the live anchor:
`One SIMPLE Change to How You Walk That Could Save Your Life | After 70`.

## Fixes
- Age values in `After 70`, `Over 60`, etc. are no longer emitted as `hook_number`.
- Pipe/channel suffixes no longer leak into `hypothesis_claim`.
- `One/A ... Change to <subject> That <modal/outcome>` anchors are decomposed into packaging, subject/action, and hypothesis claim.
- Added generic curiosity detection for `SINGLE_CHANGE` and high-stakes modal outcomes.
- Preserved the exact original `anchor_title`; parsing uses a cleaned semantic working copy only.
- No topic-specific words or neuropathy/walking hardcoding were added.

## Live expected map
- hook_number: empty
- hook_packaging: `One SIMPLE Change`
- core_subject_action: `How You Walk`
- hypothesis_claim: `Could Save Your Life`
- audience_filter: `After 70`
- curiosity_device includes `SINGLE_CHANGE`, `HIGH_STAKES_OUTCOME`

## Tests
Focused Anchor-First parser suite: 8 passed.
Full suite: 539 passed, 8 failed.
The 8 failures are outside this parser change: 1 pre-existing frozen A/B/C vocabulary expectation and 7 tests whose required project production fixtures are absent from the supplied ZIP.
