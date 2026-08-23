**File 13 of 33 — `Knowledge/13_Prompt_Library.md`**

```markdown
# 13 — Prompt Library

> Permanent internal documentation. Senior Health YouTube Production System.
> This document is standalone and self-contained.
> One canonical prompt per category. Duplicates are removed.

---

## 1. Topic Discovery

```
Scan the Senior Health niche for [SUBTOPIC].
Identify high-fear, low-competition angles not covered by existing content.
Score each on Opportunity, Competition, Evergreen, CTR, and Viewer Interest (1–10).
Compute opportunity via the standard formula.
Explain why competitors missed each.
Exclude any topic with competition >= 7 unless a relief or curiosity anchor is viable.
Return a ranked list.
```

---

## 2. Research

```
For the claim '[CLAIM]', find the strongest supporting evidence using the
Tier 1–4 evidence hierarchy.
Provide one citable source, the physiological mechanism in plain language,
and any contraindications.
If the claim cannot be supported at Tier 1–4, set citation to null and flag 'CUT'.
```

---

## 3. Title Generation

```
Generate 5 titles for a video about [TOPIC] / [PAYOFF].
Apply the master formula: Self-ID + Withheld Detail + Emotional Anchor + Specific Payoff.
Use the [FEAR / RELIEF / CURIOSITY / HOPE] anchor.
Length 8–13 words. No implausible numbers. Do not fully disclose the answer.
Apply generation rules TR1–TR7.
Rank by predicted CTR and return with the template used for each.
```

---

## 4. Thumbnail

```
Produce a thumbnail spec for [TOPIC] using the master recipe:
dark background, 2–4 yellow/red words, one emotional face (right third),
one oversized hero object, one signal icon.
Layout class: [RELIEF_FOOD / DIAGNOSTIC / NAMED_DRUG / TRANSFORMATION].
Enforce visual rules V1–V6.
Provide 5 concept variations and identify the dominant word.
```

---

## 5. Hook

```
Write a 60-second hook for [TOPIC] using the five-beat architecture:
pattern interrupt → self-ID → emotional anchor → credibility + statistic → open loop.
Opening strategy: [O1–O6].
Enforce hook rules HR1–HR4.
Return per-beat text keyed by beat number.
```

---

## 6. Full Script

```
Write a complete script for [TITLE] using the script state machine.
Maintain a curiosity loop every 60–90 seconds.
Reveal items in ascending importance and restate the strongest payoff near the end.
Include one cited Tier 1–4 study and a consult-your-clinician caveat.
Enforce invariants I1–I6.
Return the script and its loop map.
```

---

## 7. Fact-check

```
Review this script. Flag every factual claim without a Tier 1–4 source.
Identify any misrepresented statistic or overpromise.
Check for individual diagnosis, cure promises, and medication-alteration instructions.
Confirm a clinician caveat is present.
Return pass/fail with itemized violations (rule ID + location).
Result = fail if any block-severity rule is violated.
```

---

## 8. Prompt Governance

1. One canonical prompt per category; no duplicates.
2. Prompts reference rule IDs rather than restating rules, so upstream rule changes propagate automatically.
3. New prompts are added only when a genuinely new task category emerges.

---

*End of document.*
```
