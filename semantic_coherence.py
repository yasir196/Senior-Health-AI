from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from collections import Counter

_TIME_GROUPS = {
    "morning": {"morning", "dawn", "daybreak", "sunrise", "breakfast"},
    "day": {"daytime", "daylight", "midday", "afternoon", "sunlit"},
    "evening": {"evening", "dusk", "sunset", "twilight"},
    "night": {"night", "nighttime", "bedtime", "overnight", "moonlight", "bedside"},
}
_CONFLICTING_TIME_GROUPS = {
    "morning": {"evening", "night"},
    "day": {"night"},
    "evening": {"morning"},
    "night": {"morning", "day"},
}
_STOP = {
    "the","and","for","with","that","this","from","into","while","when","where","your","their","about","than","then","only","over","under","after","before","next","image","prompt","visual","scene","narrative","purpose","context","final","photorealistic","documentary","senior","health","realistic","natural","naturalistic","light","lighting","setting","adult","older","simple","clear","appropriate","support","supportive","show","showing","shown","use","without","unless","rather","exact","assigned","guidance","topic","closing","close"
}

@dataclass
class SemanticIssue:
    image_number: int
    category: str
    conflicting_attributes: str

@dataclass
class SemanticAudit:
    issues: list[SemanticIssue] = field(default_factory=list)
    structural_close_images: list[int] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.issues

    def by_category(self, category: str) -> list[SemanticIssue]:
        return [x for x in self.issues if x.category == category]


def _field(block: str, label: str) -> str:
    m = re.search(rf"^- {re.escape(label)}:\s*(.*)$", block, flags=re.M)
    return m.group(1).strip() if m else ""


def _alignment_score(block: str) -> int | None:
    raw = _field(block, "Alignment Score")
    if not raw:
        return None
    m = re.search(r"\b(100|[1-9]?\d)\b", raw)
    return int(m.group(1)) if m else None


def parse_prompt_blocks(text: str) -> list[tuple[int, str]]:
    chunks = re.split(r"(?=^### IMAGE \d{3}\s*$)", text, flags=re.M)
    out = []
    for chunk in chunks:
        m = re.match(r"^### IMAGE (\d{3})\s*$", chunk, flags=re.M)
        if m:
            out.append((int(m.group(1)), chunk))
    return out


def classify_structural_role(script_context: str, narrative_purpose: str = "") -> str | None:
    text = f"{narrative_purpose} {script_context}".lower()
    # Discourse-function patterns, intentionally topic-agnostic.
    close_signals = (
        r"\bsee you\b", r"\buntil next time\b", r"\bnext (?:one|video|episode)\b",
        r"\bthanks? for (?:watching|joining)\b", r"\bthank you for (?:watching|joining)\b",
        r"\bsign[- ]?off\b", r"\bepisode close\b",
    )
    if any(re.search(p, text) for p in close_signals):
        return "STRUCTURAL_CLOSE"
    if "structural" in text and any(k in text for k in ("subscribe", "closing", "closure", "cta")):
        return "STRUCTURAL"
    return None


def _time_groups(text: str) -> set[str]:
    low = text.lower()
    groups = set()
    for group, terms in _TIME_GROUPS.items():
        if any(re.search(rf"\b{re.escape(term)}\b", low) for term in terms):
            groups.add(group)
    return groups


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z][a-z'-]{2,}", text.lower())
    return [w for w in words if w not in _STOP]


def _dominant_prior_terms(blocks: list[tuple[int, str]], upto_index: int) -> set[str]:
    counts = Counter()
    for _, block in blocks[:upto_index]:
        prompt = _field(block, "Final AI IMAGE PROMPT")
        counts.update(set(_tokens(prompt)))
    if not counts:
        return set()
    # A recurring topic term must appear in multiple prior prompt blocks, not merely once.
    minimum = max(2, int(max(1, upto_index) * 0.12))
    return {term for term, count in counts.items() if count >= minimum}


def audit_semantic_coherence(text: str) -> SemanticAudit:
    blocks = parse_prompt_blocks(text)
    audit = SemanticAudit()

    for idx, (number, block) in enumerate(blocks):
        script = _field(block, "Script Context")
        narrative = _field(block, "Narrative Context")
        visual_type = _field(block, "Visual Type")
        purpose = _field(block, "Narrative Purpose")
        prompt = _field(block, "Final AI IMAGE PROMPT")
        role = classify_structural_role(script, purpose)
        if role == "STRUCTURAL_CLOSE":
            audit.structural_close_images.append(number)

        alignment = _alignment_score(block)
        if alignment is None:
            audit.issues.append(SemanticIssue(
                number,
                "narration_alignment",
                "missing mandatory Alignment Score; final prompt cannot be accepted without the muted-audio narration check",
            ))
        elif alignment < 85:
            audit.issues.append(SemanticIssue(
                number,
                "narration_alignment",
                f"Alignment Score={alignment}; required >=85 against exact Script Context and immediate Narrative Context",
            ))

        context_groups = _time_groups(" ".join((script, narrative, visual_type, purpose)))
        prompt_groups = _time_groups(prompt)
        for cg in context_groups:
            conflicts = prompt_groups & _CONFLICTING_TIME_GROUPS.get(cg, set())
            if conflicts:
                audit.issues.append(SemanticIssue(
                    number,
                    "time_of_day",
                    f"narrative/context={cg}; final-prompt cue(s)={','.join(sorted(conflicts))}",
                ))
                break

        # Also detect internally contradictory final-prompt temporal cues even if metadata is vague.
        prompt_groups_list = sorted(prompt_groups)
        internally_conflicting = False
        for pg in prompt_groups:
            if prompt_groups & _CONFLICTING_TIME_GROUPS.get(pg, set()):
                internally_conflicting = True
                break
        if internally_conflicting:
            detail = f"final prompt contains incompatible temporal cue groups: {', '.join(prompt_groups_list)}"
            if not any(i.image_number == number and i.category == "time_of_day" for i in audit.issues):
                audit.issues.append(SemanticIssue(number, "time_of_day", detail))

        if role == "STRUCTURAL_CLOSE":
            close_terms = set(_tokens(" ".join((script, narrative))))
            prompt_terms = set(_tokens(prompt))
            recurring = _dominant_prior_terms(blocks, idx)
            inherited = sorted((prompt_terms & recurring) - close_terms)
            # Only flag when multiple recurring content terms survive into a close that does not mention them.
            # This avoids treating generic objects used for neutral closure as inherited topic imagery.
            if len(inherited) >= 2:
                audit.issues.append(SemanticIssue(
                    number,
                    "structural_mismatch",
                    "STRUCTURAL_CLOSE inherited recurring prior visual terms absent from closing narration: "
                    + ", ".join(inherited[:8]),
                ))

    return audit


def render_semantic_qa(audit: SemanticAudit, rewrites_corrected: int = 0) -> str:
    setting = len(audit.by_category("setting_action"))
    time = len(audit.by_category("time_of_day"))
    purpose = len(audit.by_category("narration_purpose"))
    alignment = len(audit.by_category("narration_alignment"))
    structural = len(audit.by_category("structural_mismatch"))
    lines = [
        "## Semantic Coherence QA",
        "",
        f"Setting/action conflicts: {setting}",
        f"Time-of-day conflicts: {time}",
        f"Narration-purpose mismatches: {purpose}",
        f"Narration-alignment failures: {alignment}",
        f"Structurally inappropriate visuals: {structural}",
        f"Rewrites corrected: {rewrites_corrected}",
        f"Overall Semantic Coherence: {'PASS' if audit.passed else 'FAIL'}",
    ]
    if audit.issues:
        lines += ["", "### Unresolved Semantic Coherence Violations", ""]
        for issue in audit.issues:
            lines.append(f"- IMAGE {issue.image_number:03d} — {issue.category}: {issue.conflicting_attributes}")
    return "\n".join(lines)


def enforce_final_semantic_report(path: Path) -> SemanticAudit:
    text = path.read_text(encoding="utf-8")
    audit = audit_semantic_coherence(text)
    old = re.search(r"^## Semantic Coherence QA\s*$.*?(?=^Production Ready:|\Z)", text, flags=re.M | re.S)
    rewritten_count = len(re.findall(r"^- Rewritten:\s*YES\s*$", text, flags=re.M))
    report = render_semantic_qa(audit, rewritten_count) + "\n\n"
    if old:
        text = text[:old.start()] + report + text[old.end():]
    else:
        text = text.rstrip() + "\n\n" + report

    diversity_pass = "Overall Visual Diversity: PASS" in text
    ready = diversity_pass and audit.passed
    if re.search(r"^Production Ready:\s*(?:YES|NO)\s*$", text, flags=re.M):
        text = re.sub(r"^Production Ready:\s*(?:YES|NO)\s*$", f"Production Ready: {'YES' if ready else 'NO'}", text, flags=re.M)
    else:
        text = text.rstrip() + f"\n\nProduction Ready: {'YES' if ready else 'NO'}\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return audit
