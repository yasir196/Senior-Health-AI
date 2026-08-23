# 09 â€” Medical Research SOP

> Permanent internal documentation. Senior Health YouTube Production System.
> This document is standalone and self-contained.
> The rules in this document are IMMUTABLE. They are never modified by performance
> data or the self-improvement engine. They function as hard gates on all content.

---

## 1. Research Workflow

1. Define the specific claim the video will make.
2. Check `Evidence/topic_index.md`, `Evidence/evidence_sources.csv`, and `Evidence/claim_registry.csv` for reusable approved evidence.
3. Search for primary evidence supporting or refuting it.
4. Record the strongest single citation for on-screen use.
5. Identify the mechanism (how/why it works) in plain language.
6. Document contraindications and populations who should not act on it.
7. Flag any claim that cannot be supported -> revise or cut.

---

## 2. Evidence Hierarchy

| Tier | Source | Citable | Weight |
|------|--------|---------|--------|
| 1 | Systematic reviews / meta-analyses | Yes | 1.00 |
| 2 | Randomized controlled trials | Yes | 0.85 |
| 3 | Cohort / observational studies | Yes | 0.60 |
| 4 | Guidelines from major bodies | Yes | 0.70 |
| 5 | Expert opinion | Supporting only | 0.30 |
| 6 | Anecdote / single testimonial | No | 0.00 |

Every factual claim must trace to a Tier 1â€“4 source.

---

## 3. Fact-Check Workflow

1. Extract every factual claim from the draft.
2. Match each to a Tier 1â€“4 source.
3. Verify statistics are quoted accurately and in context.
4. Confirm no study is misrepresented to imply a stronger conclusion than it supports.
5. Cross-check any reused evidence against the Evidence Library source and claim IDs.
6. Return pass/fail with itemized violations.

---

## 4. Mechanism Explanations

Always explain **why** an intervention works at a cellular or physiological level in accessible language. Mechanism builds trust and differentiates from empty listicles.

---

## 5. Medical Writing Rules

| ID | Rule | Severity |
|----|------|----------|
| M1 | Claim traces to a Tier 1â€“4 source | Block |
| M2 | Statistic quoted in context | Block |
| M3 | No individual diagnosis | Block |
| M4 | No cure promise | Block |
| M5 | No medication-alteration instruction | Block |
| M6 | Clinician caveat present | Block |
| M7 | Correlation not stated as causation | Block |
| M8 | Mechanism explained in plain language | Warn |

---

## 6. Claim Decision Tree

Copy
CLAIM â”œâ”€ Traces to a Tier 1â€“4 source? â”‚ â”œâ”€ NO â†’ CUT or REVISE (M1 block) â”‚ â””â”€ YES â†’ continue â”œâ”€ Touches an elevated-scrutiny trigger? â”‚ â”œâ”€ YES â†’ require explicit caveat + double fact-check â”‚ â””â”€ NO â†’ single fact-check â”œâ”€ Implies causation from correlational data? â”‚ â”œâ”€ YES â†’ rewrite as association (M7 block) â”‚ â””â”€ NO â†’ continue â”œâ”€ Diagnoses / promises cure / alters meds? â”‚ â”œâ”€ YES â†’ BLOCK (M3 / M4 / M5) â”‚ â””â”€ NO â†’ PASS

Copy
---

## 7. Elevated-Scrutiny Triggers

- Medication
- Dosing
- Drug interaction
- Serious disease claim
- Reversal claim

Any content touching these requires explicit caveats and a second fact-check pass.

---

## 8. Safety Guidelines

1. Any topic touching medication, dosing, drug interactions, or serious disease requires elevated scrutiny and explicit caveats.
2. Content must comply with platform medical-misinformation policy; failure blocks publishing.
3. When evidence is weak, the claim is softened or removed â€” packaging drama never overrides factual integrity.
4. This niche serves a vulnerable audience; accuracy is both an ethical obligation and the channel's long-term survival asset.

---

## 9. Evidence Library Use

The Evidence Library is a reusable index, not a medical shortcut. Research_Agent must check it before new research, and Medical_Agent must verify that any reused source supports the exact project claim.

Rules:

1. Reuse only entries marked `approved`.
2. Recheck entries marked `needs_review`.
3. Do not cite a library entry if the current claim is stronger than the approved wording.
4. Add a review-queue item when a source looks stale, unclear, contradicted, or overused.
5. Never let the Evidence Library override `System/SYS_09_MEDICAL_RULE_ENGINE.json`.

---

*End of document.*
