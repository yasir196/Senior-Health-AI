from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EVIDENCE_CUE_RE = re.compile(r"\b(study|studies|trial|review|research|participants?|subjects?|patients?|adults?|cases?|controls?|cohort|randomi[sz]ed|systematic|meta-analysis)\b", re.I)
NUMBER_RE = re.compile(r"(?<!\w)(?:\d{4}|\d[\d,]*(?:\.\d+)?%?|\d+(?:\.\d+)?\s*(?:fold|times))\b", re.I)
CAUSAL_RE = re.compile(r"\b(causes?|caused|prevents?|prevented|cures?|cured|reverses?|reversed|reduces?|reduced|increases?|increased)\b", re.I)
ASSOCIATION_RE = re.compile(r"\b(associated with|linked to|correlated with|may|might|suggests?|support(?:s|ed)?|related to)\b", re.I)

MAX_HEADING_CHARS = 54
MAX_BULLET_CHARS = 96

@dataclass
class EvidenceCandidate:
    scene_id: str
    script_text: str
    start_seconds: float
    end_seconds: float
    heading: str
    bullets: list[str]
    source_trace: str
    claim_key: str
    script_line_start: str
    script_line_end: str
    verification_strength: int = 0
    medical_clarity: int = 0
    specificity: int = 0
    priority: int = 300
    warnings: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _norm(text: str) -> str:
    text = _clean(text).lower().replace("–", "-").replace("—", "-")
    return re.sub(r"[^a-z0-9%]+", " ", text).strip()


def _sentences(text: str) -> list[str]:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    lines = []
    for raw in text.splitlines():
        raw = re.sub(r"^\s*(?:[-*+]\s+|#{1,6}\s+|\d+[.)]\s+)", "", raw).strip()
        if not raw or raw.startswith("|") or set(raw) <= {"-", "=", "_"}:
            continue
        lines.extend(re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", raw))
    return [_clean(x) for x in lines if len(_clean(x)) >= 12]


def _tokens(text: str) -> set[str]:
    return {t for t in _norm(text).split() if len(t) > 2}


def _numbers(text: str) -> list[str]:
    return [m.group(0).replace(" ", "") for m in NUMBER_RE.finditer(text)]


def _overlap_score(a: str, b: str) -> float:
    aa, bb = _tokens(a), _tokens(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / max(1, min(len(aa), len(bb)))


def _presentation_worthy(script: str) -> bool:
    # Generic 'research suggests' alone is deliberately insufficient.
    has_specific = bool(NUMBER_RE.search(script)) or bool(re.search(r"\b(randomi[sz]ed|systematic review|meta-analysis|trial|cohort|study)\b", script, re.I))
    return bool(EVIDENCE_CUE_RE.search(script) and has_specific)


def _traceable(display: str, sources: str) -> bool:
    for n in _numbers(display):
        if n not in sources.replace(" ", ""):
            return False
    return True


def _medical_safe(display: str, medical_text: str) -> bool:
    # If approved medical text uses association language for the same claim, do not
    # permit a causal upgrade in the display wording.
    if medical_text and ASSOCIATION_RE.search(medical_text) and CAUSAL_RE.search(display) and not ASSOCIATION_RE.search(display):
        return False
    return True


def _heading(source_lines: list[str]) -> str:
    joined = " ".join(source_lines)
    year = next((n for n in _numbers(joined) if re.fullmatch(r"(?:19|20)\d{2}", n)), "")
    if re.search(r"systematic review", joined, re.I): base = "SYSTEMATIC REVIEW"
    elif re.search(r"randomi[sz]ed.*trial|randomi[sz]ed", joined, re.I): base = "RANDOMIZED TRIAL"
    elif re.search(r"\btrial\b", joined, re.I): base = "CLINICAL TRIAL"
    elif re.search(r"\bstudy\b|\bcohort\b", joined, re.I): base = "STUDY FINDING"
    else: base = "RESEARCH FINDING"
    value = f"{base} ({year})" if year else base
    return value[:MAX_HEADING_CHARS]


def _shorten(sentence: str, max_chars: int = MAX_BULLET_CHARS) -> str | None:
    s = re.sub(r"^(?:according to|the research (?:found|reported|showed) that)\s+", "", _clean(sentence), flags=re.I)
    if len(s) <= max_chars:
        return s
    # Conservative clause extraction: never silently truncate mid-fact.
    clauses = [c.strip(" ,;:") for c in re.split(r"[;]", s) if c.strip()]
    for c in clauses:
        if len(c) <= max_chars and (_numbers(c) or ASSOCIATION_RE.search(c) or EVIDENCE_CUE_RE.search(c)):
            return c
    return None


def _select_bullets(script: str, source_lines: list[str], medical_lines: list[str]) -> list[str] | None:
    ranked = sorted(source_lines, key=lambda s: (_overlap_score(script, s), bool(_numbers(s)), len(_tokens(s))), reverse=True)
    chosen: list[str] = []
    # Prefer a medical-approved line for the finding when one clearly matches.
    med = sorted(medical_lines, key=lambda s: _overlap_score(script, s), reverse=True)
    finding = med[0] if med and _overlap_score(script, med[0]) >= 0.22 else (ranked[0] if ranked else "")
    context = [s for s in ranked if s != finding]
    # Pick up to two distinct contextual facts, favoring metadata/numbers.
    for s in context:
        if len(chosen) >= 2: break
        short = _shorten(s)
        if short and _norm(short) not in {_norm(x) for x in chosen}:
            chosen.append(short)
    short_finding = _shorten(finding)
    if short_finding and _norm(short_finding) not in {_norm(x) for x in chosen}:
        chosen.append(short_finding)
    # If fewer than 3, use additional traceable source facts. No filler is invented.
    for s in ranked:
        if len(chosen) >= 3: break
        short = _shorten(s)
        if short and _norm(short) not in {_norm(x) for x in chosen}:
            chosen.append(short)
    return chosen[:3] if len(chosen) >= 3 else None


def _claim_key(script: str, bullets: list[str]) -> str:
    # Stable content key, intentionally independent of scene/timing.
    core = _norm(" ".join(bullets))
    return "EVC-" + hashlib.sha256(core.encode("utf-8")).hexdigest()[:16]


def _read(path: Path) -> str:
    try: return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError): return ""


def analyze_project_evidence(project: Path, timeline_rows: list[dict[str, Any]]) -> tuple[list[EvidenceCandidate], list[str]]:
    """Deterministically detect and verify evidence using current-project artifacts only."""
    project = Path(project).resolve()
    research_path = project / "02_research_sheet.md"
    gate1_path = project / "13_fact_check_log.md"
    gate2_path = next((p for p in (project/"15_medical_gate_2.md", project/"15_medical_gate_2_log.md") if p.is_file()), None)
    research = _read(research_path); gate1 = _read(gate1_path); gate2 = _read(gate2_path) if gate2_path else ""
    if not research or not gate1:
        return [], ["Evidence analyzer skipped: current-project Research and Medical Gate 1 are both required."]
    source_lines = _sentences(research)
    medical_lines = _sentences(gate2 or gate1)
    source_blob = research + "\n" + gate1 + "\n" + gate2
    accepted: list[EvidenceCandidate] = []
    diagnostics: list[str] = []
    for row in timeline_rows:
        script = _clean(row.get("Script Text", ""))
        scene_id = _clean(row.get("Scene ID", ""))
        if not _presentation_worthy(script):
            continue
        matches = [s for s in source_lines if _overlap_score(script, s) >= 0.22]
        if not matches:
            diagnostics.append(f"{scene_id}: EVIDENCE_DROPPED_SOURCE_UNVERIFIED")
            continue
        matches = sorted(matches, key=lambda s: _overlap_score(script, s), reverse=True)[:8]
        med_matches = [s for s in medical_lines if _overlap_score(script, s) >= 0.18]
        bullets = _select_bullets(script, matches, med_matches)
        if not bullets or len(bullets) != 3:
            diagnostics.append(f"{scene_id}: EVIDENCE_DROPPED_INSUFFICIENT_3_BULLETS")
            continue
        display = " ".join(bullets)
        if not _traceable(display, source_blob):
            diagnostics.append(f"{scene_id}: EVIDENCE_DROPPED_NUMBER_MISMATCH")
            continue
        medical_context = " ".join(med_matches)
        if not _medical_safe(display, medical_context):
            diagnostics.append(f"{scene_id}: EVIDENCE_DROPPED_MEDICAL_WORDING_CONFLICT")
            continue
        heading = _heading(matches)
        if not _traceable(heading, source_blob):
            diagnostics.append(f"{scene_id}: EVIDENCE_DROPPED_HEADING_METADATA_MISMATCH")
            continue
        start = float(row.get("_start", 0.0) or 0.0); end = float(row.get("_end", 0.0) or 0.0)
        if end <= start:
            diagnostics.append(f"{scene_id}: EVIDENCE_DROPPED_INVALID_TIMING")
            continue
        trace = json.dumps({
            "project": project.name,
            "scene_id": scene_id,
            "script": script,
            "source_file": research_path.name,
            "source_matches": matches[:3],
            "medical_file": (gate2_path.name if gate2_path else gate1_path.name),
            "medical_matches": med_matches[:2],
            "normalized_claim": _norm(display),
        }, ensure_ascii=False, sort_keys=True)
        accepted.append(EvidenceCandidate(scene_id, script, start, end, heading, bullets, trace,
                                          _claim_key(script, bullets), script, script,
                                          verification_strength=3, medical_clarity=2 if med_matches else 1,
                                          specificity=sum(bool(_numbers(x)) for x in matches)))
    # Duplicate claim suppression: best fit wins, then earliest scene/timing.
    winners: dict[str, EvidenceCandidate] = {}
    for c in accepted:
        rank = (c.verification_strength, c.medical_clarity, c.specificity, -c.start_seconds, c.scene_id)
        old = winners.get(c.claim_key)
        if old is None:
            winners[c.claim_key] = c
        else:
            old_rank = (old.verification_strength, old.medical_clarity, old.specificity, -old.start_seconds, old.scene_id)
            if rank > old_rank:
                diagnostics.append(f"{old.scene_id}: EVIDENCE_DROPPED_DUPLICATE_CLAIM")
                winners[c.claim_key] = c
            else:
                diagnostics.append(f"{c.scene_id}: EVIDENCE_DROPPED_DUPLICATE_CLAIM")
    return sorted(winners.values(), key=lambda c: (c.start_seconds, c.scene_id)), diagnostics
