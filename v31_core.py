from __future__ import annotations

import csv, hashlib, json, os, re, shlex, shutil, subprocess
from decimal import Decimal, ROUND_HALF_UP
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

WORKFLOW_STAGES = [
    "Topic Validation", "Research + Medical Gate 1", "Thumbnail",
    "Script Outline", "Prepare Opus Package", "Writer Workspace", "Narrative QA",
    "Medical Gate 2", "Speech Optimizer", "Production Package", "SEO", "Final QA + Summary",
]
PIPELINE = [
    ("Topic Validation", "01_topic_validation.md"), ("Research + Medical Gate 1", "02_research_sheet.md"),
    ("Thumbnail", "04_thumbnail_concepts.md"),
    ("Script Outline", "05_script_outline.md"), ("Prepare Opus Package", "opus_writer_package.md"),
    ("Writer Workspace", "06_final_script.md"), ("Narrative QA", "14_narrative_qa.md"),
    ("Medical Gate 2", "15_medical_gate_2.md"), ("Speech Optimizer", "06a_voice_script.md"),
    ("Production Package", "07_production_sheet.csv"), ("SEO", "08_youtube_metadata.md"),
    ("Final QA + Summary", "16_project_summary.md"),
]
STAGE_FILES = dict(PIPELINE)
PASS_VALUES = {"PASS", "PASSED", "APPROVED", "READY"}
CONDITIONAL_VALUES = {"PASS WITH SUGGESTIONS", "PASS WITH REVISIONS", "PASS WITH REQUIRED EDITS", "CONDITIONAL PASS", "PASS_WITH_SUGGESTIONS"}
FAIL_VALUES = {"FAIL", "FAILED", "BLOCKED", "REJECTED"}
ALLOWED_SCRIPT_EXTENSIONS = {".md", ".txt"}
DEFAULT_REQUIRED_HEADINGS = ["hook", "introduction", "main content", "conclusion"]
QA_REPORTS = {
    "Narrative QA": "14_narrative_qa.md", "Medical Gate 2": "15_medical_gate_2.md",
    "Speech Optimizer": "06b_voice_checklist.md", "Production Cleaner": "production_clean_report.md",
}
WRITER_OUTPUTS = ["06_final_script.md", "06_runtime_report.md", "06_retention_report.md", "06_medical_review.md", "06_humanization_report.md"]

PRODUCTION_OUTPUT_FILES = ["07_production_sheet.csv", "10_image_prompts.md", "12_broll_prompts.md"]


def resolve_title_anchor(project: Path, explicit_anchor: str | None = None) -> str | None:
    """Normalize the authoritative orchestrator-supplied Title anchor only.

    The project Anchor / Outlier Title is the immutable user-supplied winning title.
    It is stored in project.json and is the single title source of truth for validation,
    research, thumbnail, script, production, SEO, and QA. No title generation stage exists.

    ``project`` is retained in the signature for compatibility with existing callers;
    it is intentionally not consulted for anchor resolution.
    """
    explicit=(explicit_anchor or "").strip()
    if explicit:
        return explicit
    # Anchor-First projects persist the user-supplied outlier separately from the
    # generic project topic. This is an authorized orchestrator state, not an
    # inference from topic/slug/research/generated artifacts.
    meta_path=Path(project)/"project.json"
    if meta_path.is_file():
        try:
            meta=json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            meta={}
        persisted=str(meta.get("anchor_title") or "").strip()
        if persisted:
            return persisted
    return None


ANCHOR_CLAIM_MAP_FILE = "01a_anchor_claim_map.json"
TITLE_REPAIR_BLUEPRINT_FILE = "13a_title_repair_blueprint.json"


def build_anchor_claim_map(anchor_title: str) -> dict[str, Any]:
    """Parse anchor packaging roles without deciding whether its medical claim is true.

    Important semantic rules:
    - age numbers (After 70 / Over 60) are audience filters, never hook counts;
    - decorative/channel suffixes after ``|`` are not part of the medical claim;
    - ``One ... Change to <subject> That Could/May/... <outcome>`` keeps the
      change as packaging, the subject/action as WHAT, and the outcome as the
      hypothesis claim;
    - parsing is heuristic and project-generic: it must not contain topic words
      such as neuropathy, walking, beetroot, etc.
    """
    raw=(anchor_title or "").strip()
    if not raw:
        raise ValueError("TITLE_RUNTIME_ANCHOR_MISSING")

    # Preserve the exact user-supplied anchor, but parse a clean working copy.
    title=raw
    audience_match=re.search(
        r"\b(?:after|over|age(?:d)?(?:\s+of)?)\s+\d{2,3}\b|\bseniors?\b|\bolder adults?\b",
        title, re.I,
    )
    audience=audience_match.group(0).strip() if audience_match else ""

    # A pipe commonly separates channel packaging or an audience suffix. Keep an
    # audience-bearing suffix, discard other pipe suffixes from semantic parsing.
    parts=[x.strip() for x in title.split("|")]
    semantic=parts[0]
    if len(parts) > 1:
        for suffix in parts[1:]:
            if audience and re.search(re.escape(audience), suffix, re.I):
                semantic=f"{semantic} {suffix}".strip()

    # Hook count: first integer that is NOT inside an age/audience expression.
    age_spans=[]
    for m in re.finditer(r"\b(?:after|over|age(?:d)?(?:\s+of)?)\s+(\d{2,3})\b", semantic, re.I):
        age_spans.append(m.span(1))
    number=""
    for m in re.finditer(r"\b\d+\b", semantic):
        if not any(a <= m.start() and m.end() <= b for a,b in age_spans):
            number=m.group(0)
            break

    anatomy_match=re.search(
        r"\b(?:in|for)\s+([^?|:]+?)(?=\s+(?:after|over)\s+\d{2,3}\b|$)",
        semantic, re.I,
    )
    anatomy=anatomy_match.group(1).strip(" :-|") if anatomy_match else ""

    hook=""
    subject=""
    claim=""

    # Pattern: "One SIMPLE Change to How You Walk That Could Save Your Life".
    change_match=re.match(
        r"^(?P<hook>(?:one|a)\b.+?\bchange)\s+to\s+(?P<subject>.+?)\s+that\s+"
        r"(?P<claim>(?:could|can|may|might|will|helps?|supports?|reduces?|eases?|improves?|increases?|decreases?|prevents?|saves?)\b.+?)"
        r"(?=\s+(?:after|over)\s+\d{2,3}\b|$)",
        semantic, re.I,
    )
    if change_match:
        hook=change_match.group("hook").strip(" :-|")
        subject=change_match.group("subject").strip(" :-|")
        claim=change_match.group("claim").strip(" :-|")
    else:
        # Generic clause extraction used by list/exercise/food anchors.
        claim_match=re.search(
            r"\b(?:that|to|for)\s+(.+?)(?=\s+(?:in|for)\s+[^?|:]+?(?:\s+(?:after|over)\s+\d{2,3})?$|\s+(?:after|over)\s+\d{2,3}\b|$)",
            semantic, re.I,
        )
        hook_end=claim_match.start() if claim_match else len(semantic)
        hook=semantic[:hook_end].strip(" :-|")
        claim=claim_match.group(1).strip(" :-|") if claim_match else ""
        subject=hook

    skeleton=semantic
    # Replace the most semantic-specific spans first to avoid partial overlap.
    replacements=((claim,"HYPOTHESIS_CLAIM"),(subject,"CORE_SUBJECT_ACTION"),(anatomy,"ANATOMY_TARGET"),(audience,"AUDIENCE"))
    for value,label in sorted(replacements, key=lambda x: len(x[0]), reverse=True):
        if value:
            skeleton=re.sub(re.escape(value), f"[{label}]", skeleton, count=1, flags=re.I)
    skeleton=re.sub(r"\s+", " ", skeleton).strip(" |")

    curiosity=[]
    if "?" in title: curiosity.append("QUESTION")
    if re.search(r"\bthis\b", title, re.I): curiosity.append("WITHHOLD_THIS")
    if re.search(r"\bmistake\b", title, re.I): curiosity.append("MISTAKE")
    if re.search(r"\bwarning|warn|don't|before\b", title, re.I): curiosity.append("WARNING_OR_BEFORE")
    if re.search(r"\b(?:one|a)\b.+?\bchange\b", semantic, re.I): curiosity.append("SINGLE_CHANGE")
    if re.search(r"\b(?:could|can|may|might)\s+(?:save|change|transform|protect)\b", semantic, re.I): curiosity.append("HIGH_STAKES_OUTCOME")

    frozen=[]
    for value in (hook, subject, anatomy, audience):
        if value and value not in frozen:
            frozen.append(value)

    return {
        "schema_version":"anchor_claim_map_v1",
        "anchor_title":raw,
        "hook_number":number,
        "hook_packaging":hook,
        "core_subject_action":subject,
        "hypothesis_claim":claim,
        "anatomy_target":anatomy,
        "audience_filter":audience,
        "curiosity_device":curiosity,
        "sentence_skeleton":skeleton,
        "frozen_candidate_tokens":frozen,
        "medical_status":"UNVERIFIED_HYPOTHESIS",
    }


def write_anchor_claim_map(project: Path, anchor_title: str) -> Path:
    data=build_anchor_claim_map(anchor_title)
    path=Path(project)/ANCHOR_CLAIM_MAP_FILE
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return path


def load_title_repair_blueprint(project: Path, anchor_title: str) -> dict[str, Any]:
    """Load Phase-2 Medical Gate repair boundary and bind it to the exact runtime anchor."""
    path=Path(project)/TITLE_REPAIR_BLUEPRINT_FILE
    if not path.is_file():
        raise ValueError(f"{TITLE_REPAIR_BLUEPRINT_FILE} is missing for anchor-first title generation")
    data=json.loads(path.read_text(encoding="utf-8-sig"))
    recorded=str(data.get("anchor_title") or data.get("original_anchor") or "").strip()
    if recorded != (anchor_title or "").strip():
        raise ValueError("TITLE_REPAIR_BLUEPRINT_ANCHOR_MISMATCH")
    if not data.get("supported_claim_boundary") and not data.get("supported_replacement_lane"):
        raise ValueError("TITLE_REPAIR_BLUEPRINT_BOUNDARY_MISSING")
    return data


def minimum_transformation_context(project: Path, anchor_title: str) -> str:
    """Render the authoritative Phase-3 writer contract from current project artifacts."""
    project=Path(project); anchor=(anchor_title or "").strip()
    if not anchor: return ""
    cmap_path=project/ANCHOR_CLAIM_MAP_FILE
    if not cmap_path.is_file():
        write_anchor_claim_map(project, anchor)
    cmap=json.loads(cmap_path.read_text(encoding="utf-8-sig"))
    if str(cmap.get("anchor_title","")).strip()!=anchor:
        raise ValueError("ANCHOR_CLAIM_MAP_ANCHOR_MISMATCH")
    bp_path=project/TITLE_REPAIR_BLUEPRINT_FILE
    if not bp_path.is_file():
        # Backward compatibility for pre-Phase-2 projects/tests. Phase 3 activates only
        # when Medical Gate has emitted its repair blueprint. Existing anchor behavior
        # remains intact instead of silently fabricating a repair boundary.
        return "\nANCHOR-FIRST PHASE 3: DEFERRED — no current Medical Gate repair blueprint; do not fabricate one.\n"
    bp=load_title_repair_blueprint(project, anchor)
    return (
        "\nANCHOR-FIRST PHASE 3 — MINIMUM NECESSARY TRANSFORMATION (AUTHORITATIVE)\n"
        f"Claim Map: {json.dumps(cmap, ensure_ascii=False)}\n"
        f"Medical Repair Blueprint: {json.dumps(bp, ensure_ascii=False)}\n"
        "The outlier controls packaging architecture; evidence controls factual claims. "
        "Freeze every compliant anchor component by default. Modify only the smallest span required by the Medical Repair Blueprint. "
        "After EVERY proposed repair, re-audit the COMPLETE resulting claim/title against current Research + Medical Gate 1; a synonym does not inherit compliance. "
        "If a 0-10% repair cannot pass, Tier 1 MUST contain zero candidates and its quota migrates forward. Never manufacture an unsafe title to satisfy a tier quota. "
        "Generate exactly 15 unique candidates using realized safe tiers: Tier 1 0-10%, Tier 2 10-20%, Tier 3 20-35%, Tier 4 controlled experimentation. "
        "Use the lowest-transformation safe neighborhood first; broader experimentation comes only after minimum repairs. "
        "Transformation percentage is a fidelity/ranking signal only, never a medical-safety gate. "
        "Do not invent Doctor-Approved, clinician authority, outcomes, symptoms, mechanisms, or qualifiers not supported by THIS project. "
        "Do not choose WINNER, SAFE_ALTERNATIVE, or HIGH_UPSIDE_EXPERIMENT during candidate generation; selection belongs to the Judge/deterministic analysis layer. "
        "The final candidate collection must still contain at least 8 titles that genuinely satisfy the existing deterministic A/B/C anchor classifier."
    )



class ManualTitleImportError(ValueError):
    pass


def parse_manual_title_txt(path: Path) -> list[str]:
    """Parse an explicitly selected manual-title TXT file without rewriting title wording."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ManualTitleImportError("Manual title import: FAIL\nTXT file must be UTF-8 (UTF-8 BOM is supported).") from exc
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if any(not line.strip() for line in lines):
        raise ManualTitleImportError("Manual title import: FAIL\nBlank title/line found inside the candidate list.")

    titles: list[str] = []
    title_prefix = re.compile(r"^TITLE_?(?:0?[1-9]|1[0-5])\s*:\s*", re.IGNORECASE)
    number_prefix = re.compile(r"^(?:[1-9]|1[0-5])\s*[.)]\s*")
    for pos, raw in enumerate(lines, 1):
        value = raw.strip()
        value = title_prefix.sub("", value, count=1)
        value = number_prefix.sub("", value, count=1)
        value = value.strip()
        if not value:
            raise ManualTitleImportError(f"Manual title import: FAIL\nEmpty title found at position {pos}.")
        titles.append(value)

    if len(titles) != 15:
        raise ManualTitleImportError(f"Manual title import: FAIL\nExpected 15 titles, found {len(titles)}.")
    seen: dict[str, int] = {}
    for pos, title in enumerate(titles, 1):
        if title in seen:
            raise ManualTitleImportError(
                f"Manual title import: FAIL\nDuplicate titles found at positions {seen[title]} and {pos}."
            )
        seen[title] = pos
    return titles



class ManualTitleJudgeImportError(ValueError):
    pass


def import_manual_title_judge_csv(project: Path, judge_csv_path: Path, manual_titles: list[str], anchor_outlier_pattern: str | None = None) -> list[str]:
    """Import an Opus/manual Judge V2 CSV, then canonicalize + deterministically validate it.

    The Judge may score/rank, but title strings remain immutable. Runtime code remains
    authoritative for anchor flags, Content-Promise Bond, final recommendation wiring,
    serialization synchronization, and the final PASS/FAIL.
    """
    project=Path(project); judge_csv_path=Path(judge_csv_path)
    try:
        with judge_csv_path.open(encoding="utf-8-sig", newline="") as h:
            reader=csv.DictReader(h); rows=list(reader); header=reader.fieldnames or []
    except Exception as exc:
        return [f"Manual Judge import could not parse CSV: {exc}"]
    if header != TITLE_V2_EXACT_HEADER:
        return ["Manual Judge CSV header does not match exact Title V2 schema"]
    if len(rows) != 15:
        return [f"Manual Judge CSV must contain exactly 15 rows; found {len(rows)}"]
    imported=[(r.get("title") or "").strip() for r in rows]
    expected=list(manual_titles)
    if len(expected) != 15 or len(set(expected)) != 15:
        return ["Manual Writer title set must contain exactly 15 unique titles"]
    if set(imported) != set(expected) or len(set(imported)) != 15:
        return ["Manual Judge immutability violation: Judge CSV titles must equal the 15 Writer titles exactly"]

    # Seed current-run artifacts. Canonicalizer owns all deterministic fields afterward.
    csv_path=project/"03_titles.csv"; md_path=project/"03_titles.md"
    with csv_path.open("w",encoding="utf-8-sig",newline="") as h:
        w=csv.DictWriter(h,fieldnames=TITLE_V2_EXACT_HEADER,extrasaction="ignore",lineterminator="\n")
        w.writeheader(); w.writerows(rows)
    md_path.write_text(
        "# Title Validation Report\n\n"
        "## Title Strategy Summary\n\nManual Opus Judge import; deterministic runtime canonicalization is authoritative.\n\n"
        "## Title Risk Report\n\nManual Judge scoring imported; deterministic runtime checks follow.\n",
        encoding="utf-8",
    )
    issues=canonicalize_title_v2_artifacts(project, anchor_outlier_pattern)
    if not issues:
        issues=validate_manual_title_candidate_set(project, expected)
    if not issues:
        issues=validate_title_v2_artifacts(project, anchor_outlier_pattern)
    write_title_v2_validation_result(project, issues)
    # Re-run after writing the authoritative result so the on-disk artifact is the one validated.
    if not issues:
        post=validate_title_v2_artifacts(project, anchor_outlier_pattern)
        if post:
            issues=post; write_title_v2_validation_result(project, issues)
    return issues

def assert_manual_title_handoff(parsed_manual_titles: list[str], canonical_candidate_titles: list[str] | tuple[str, ...]) -> None:
    """Deterministic pre-analysis guard: manual parser output must equal the canonical candidate pool position-for-position."""
    expected = tuple(parsed_manual_titles)
    actual = tuple(canonical_candidate_titles)
    if expected != actual:
        raise ManualTitleImportError("Manual TXT immutability violation")


def validate_manual_title_candidate_set(project: Path, manual_titles: list[str]) -> list[str]:
    """Fail if serialized artifacts changed, removed, duplicated, or invented manual title text."""
    csv_path = Path(project) / "03_titles.csv"
    if not csv_path.is_file():
        return ["manual title validation requires 03_titles.csv"]
    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception as exc:
        return [f"manual title validation could not parse 03_titles.csv: {exc}"]
    actual = [row.get("title", "") for row in rows]
    if len(actual) != 15:
        return [f"Manual TXT immutability violation: expected 15 titles, found {len(actual)}"]
    if len(set(actual)) != 15:
        return ["Manual TXT immutability violation: output contains duplicate titles"]
    expected = list(manual_titles)
    if set(actual) != set(expected):
        missing = [t for t in expected if t not in actual]
        added = [t for t in actual if t not in expected]
        detail=[]
        if missing: detail.append(f"missing imported title(s): {missing!r}")
        if added: detail.append(f"unexpected/rewritten title(s): {added!r}")
        return ["Manual TXT immutability violation: " + "; ".join(detail)]
    return []


def build_manual_title_stage_instruction(project_name: str, titles: list[str], anchor_outlier_pattern: str | None = None) -> str:
    """Enter the existing V2 pipeline at the post-generation analysis boundary with immutable manual candidates."""
    if len(titles) != 15 or len(set(titles)) != 15 or any(not t.strip() for t in titles):
        raise ManualTitleImportError("Manual title import: FAIL\nExactly 15 non-empty unique titles are required.")
    canonical_candidate_titles = tuple(titles)
    assert_manual_title_handoff(titles, canonical_candidate_titles)
    ref = f"Projects/{project_name}/"
    anchor = anchor_outlier_pattern.strip() if anchor_outlier_pattern and anchor_outlier_pattern.strip() else None
    runtime_context = (
        f"Anchor Outlier Pattern:\n{anchor}\nTreat the Anchor Outlier Pattern as PROVIDED."
        if anchor else "Anchor Outlier Pattern: unavailable"
    )
    rendered = "\n".join(f"TITLE_{i:02d}: {title}" for i, title in enumerate(canonical_candidate_titles, 1))
    return (
        f"For {ref}, perform the EXISTING Title Agent V2 POST-CANDIDATE ANALYSIS only. "
        "Candidate generation has already happened externally and is BYPASSED for this run. "
        "Load and apply the existing Title Agent V2 analysis/scoring/ranking/selection contracts and exactly the approved required project files: "
        "01_topic_validation.md, 02_research_sheet.md, 13_fact_check_log.md. Optional project files remain optional.\n"
        f"{runtime_context}\n"
        "MANUAL TXT MODE — ANALYZE ONLY. Do NOT execute any Title_Agent workflow step that creates, generates, regenerates, replaces, repairs, improves, medically rewrites, backfills, or discards candidate title wording. "
        "Do NOT run anchor-first generation. Do NOT create replacement candidates for Medical Gate failures, weak scores, family distribution, experimental rules, or an anchor shortfall. "
        "The 15 strings below ARE the canonical candidate collection before analysis, position-for-position. Treat their title fields as read-only immutable identifiers. "
        "Your task starts AFTER candidate generation: evaluate these exact strings with the existing Medical Gate, family classification, packaging/hook analysis, scoring components, viewer curiosity, search intent, packaging confidence, medical risk, experimental classification, and selection logic. "
        "You may assign metadata and rank the records, but you may NEVER edit the title field. If a title fails a gate, preserve it exactly and flag/report the failure; do not replace it. "
        "If fewer than 8 titles pass the deterministic anchor audit, preserve all titles and allow the deterministic validator to FAIL with the real count. "
        "Create only 03_titles.md and 03_titles.csv from this exact immutable candidate set. Do not write 'Pending deterministic canonicalization', do not pre-write an anchor count, and do not claim PASS pending validation; the Python deterministic layer is authoritative after serialization.\n\n"
        "IMMUTABLE CANONICAL CANDIDATE COLLECTION:\n" + rendered
    )

def title_anchor_context(anchor_outlier_pattern: str | None) -> str:
    """Return the exact orchestrator runtime value for Title_Agent's optional anchor."""
    if anchor_outlier_pattern is None or not anchor_outlier_pattern.strip():
        return "Anchor Outlier Pattern: unavailable"
    return f"Anchor Outlier Pattern: {anchor_outlier_pattern}"


def build_title_stage_instruction(project_name: str, anchor_outlier_pattern: str | None = None) -> str:
    ref = f"Projects/{project_name}/"
    anchor = anchor_outlier_pattern if anchor_outlier_pattern is not None and anchor_outlier_pattern.strip() else None
    if anchor is None:
        runtime_context = "Anchor Outlier Pattern: unavailable"
    else:
        runtime_context = (
            "Additionally, use this authorized Orchestrator runtime context:\n"
            "Anchor Outlier Pattern:\n"
            f"{anchor}\n"
            "Treat the Anchor Outlier Pattern as PROVIDED. Do not treat it as unavailable merely because it is not a project file. ANCHOR-FIRST GENERATION IS MANDATORY when the supplied anchor is medically adjustable: build the first 8 of the 15 candidates on the safe anchor skeleton BEFORE generating any free/non-anchor candidate. Derive the construction lanes from THIS project only: (A) WHO/audience from the runtime anchor, (B) WHAT/subject-action lane from the runtime anchor plus current Research, and (C) WHY/payoff lane only from current Research + Medical Gate 1-approved meaning. Do not import subject/payoff vocabulary from another project or from examples. Self-check all 8 anchor-first titles against the same project-derived A/B/C semantics used by the deterministic runtime classifier; replace any failed anchor-first candidate immediately. Do not proceed to the remaining <=7 free titles until 8 compliant anchor-first titles are present in the final 15. Do not satisfy the quota by merely writing anchor_variation=YES on a non-matching title. The runtime will recompute anchor_variation deterministically from title text and will FAIL the stage if fewer than 8 true matches remain. Packaging strength is evaluated only after Medical Safety and A/B/C; it cannot make an unsafe title eligible or fabricate an anchor PASS."
        )
    return (
        f"For {ref}, run Title_Agent using exactly its approved required project files: "
        "01_topic_validation.md, 02_research_sheet.md, 13_fact_check_log.md. "
        "Optional project files are 00_topic_ideas.md and 01b_outlier_references.md; their absence must not halt Title_Agent.\n"
        "The project-file restriction applies only to project files and does not exclude authorized Orchestrator runtime context. "
        "Runtime context supplied in this instruction remains authoritative after Title_Agent.md and system contracts are loaded; "
        "do not reconstruct optional orchestrator inputs from project files or downgrade a supplied value to unavailable.\n"
        f"{runtime_context}\n"
        + (minimum_transformation_context(Path("Projects") / project_name, anchor) if anchor and (Path("Projects") / project_name).exists() else "") + "\n"
        "Create only 03_titles.md and 03_titles.csv according to the active Title_Agent V2 contract."
    )


def generated_anchor_variation_count(project: Path, anchor_outlier_pattern: str | None) -> int | None:
    """Count true A/B/C anchor titles in the freshly generated CSV before canonicalization."""
    anchor=(anchor_outlier_pattern or "").strip()
    csv_path=project/"03_titles.csv"
    if not anchor or not csv_path.is_file():
        return None
    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as h:
            reader=csv.DictReader(h)
            rows=list(reader)
    except Exception:
        return None
    if len(rows) != 15 or not reader.fieldnames or "title" not in reader.fieldnames:
        return None
    return sum(classify_anchor_variation(row.get("title", ""), anchor, project=project)[0] for row in rows)


def build_title_anchor_regeneration_instruction(project_name: str, anchor_outlier_pattern: str, found: int) -> str:
    """Correct a generated set that drifted below the required project-derived anchor-first minimum."""
    base=build_title_stage_instruction(project_name, anchor_outlier_pattern)
    return (
        base + "\n\n"
        "ANCHOR-FIRST GENERATION CORRECTION — the immediately previous generated set contained "
        f"only {found} deterministic A/B/C anchor variations, so it is rejected before canonicalization. "
        "Repair the current 15-title candidate set at the GENERATION stage; do not relabel non-matches. Preserve every "
        "existing title that already deterministically passes A/B/C. Also preserve the current winner, SAFE_ALTERNATIVE, "
        "all finalists, and the highest-upside experiment even when one of those protected rows is non-anchor. Generate enough "
        "additional medically safe anchor-skeleton candidates to reach at least eight true matches. do not generate candidate 9 until candidates 1-8 each literally pass A, B, and C under the current project-derived classifier. Derive every added title's "
        "A=WHO, B=WHAT, and C=WHY/payoff lanes from the supplied runtime anchor and THIS project's Topic Validation, Research, "
        "and Medical Gate 1 only. Do not import vocabulary or examples from another topic. Keep the final set at exactly 15 by "
        "removing only the lowest-ranked NON-anchor rows that are not protected as winner, SAFE_ALTERNATIVE, finalist, or "
        "highest-upside experiment. Then score normally and re-rank by overall_score DESC using the existing unchanged tie-break "
        "chain. Do not alter Medical Gate rules, frozen A/B/C semantics, family rules, experimental rules, or labels to force the "
        "quota. The deterministic runtime classifier, not your label, decides the count."
    )


def assert_title_anchor_runtime_context(prompt: str, anchor_outlier_pattern: str | None) -> tuple[bool, str]:
    """Validate the exact Title anchor handoff immediately before Codex execution."""
    anchor = anchor_outlier_pattern if anchor_outlier_pattern is not None and anchor_outlier_pattern.strip() else None
    if anchor is None:
        ok = "Anchor Outlier Pattern: unavailable" in prompt
        return ok, "title_anchor_present = False" if ok else "missing unavailable anchor marker"
    required = f"Anchor Outlier Pattern:\n{anchor}"
    if required not in prompt:
        return False, "exact anchor value is missing from final Title instruction"
    if "Anchor Outlier Pattern: unavailable" in prompt:
        return False, "final Title instruction contradicts provided anchor with unavailable marker"
    return True, f"title_anchor_present = True\ntitle_anchor_value = {anchor}"


def write_title_anchor_runtime_diagnostic(log_dir: Path, project: Path, prompt: str, anchor_outlier_pattern: str | None, root: Path) -> Path:
    """Write a secret-free Title-stage handoff diagnostic immediately before run_codex()."""
    ok, status = assert_title_anchor_runtime_context(prompt, anchor_outlier_pattern)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{project.name}_title_anchor_runtime_context.md"
    body = (
        "# Title Anchor Runtime Diagnostic\n\n"
        f"Validation: {'PASS' if ok else 'FAIL'}\n\n"
        f"{status}\n\n"
        f"cwd = {root}\n\n"
        "## Final Title Stage Instruction Immediately Before run_codex()\n\n"
        "```text\n" + prompt + "\n```\n"
    )
    write_text(path, body)
    return path


TITLE_V2_RECOMMENDATION_TYPES = {"WINNER", "SAFE_ALTERNATIVE", "HIGH_UPSIDE_EXPERIMENT", "FINALIST", "STANDARD"}
TITLE_V2_THUMBNAIL_EMOTIONS = {"Curiosity", "Concern", "Hope", "Surprise", "Relief", "Urgency"}
TITLE_V2_PUBLISH_RECOMMENDATIONS = {"PRIORITY", "STRONG", "TEST", "HOLD"}
TITLE_V2_EXACT_HEADER = "rank,title,title_family,packaging_style,hook_used,anchor_variation,target_audience,consensus_fit,medical_safety,audience_fit,viewer_benefit,viewer_curiosity_raw,viewer_curiosity_weighted,search_intent_type,search_intent_score,thumbnail_compatibility,novelty,clarity,overall_score,packaging_confidence,risk_level,risk_note,experimental,finalist,recommendation_type,recommended_thumbnail_direction,thumbnail_must_not_repeat,primary_viewer_problem,primary_research_mechanism,thumbnail_emotion,publish_recommendation".split(",")
TITLE_PROMISE_HOOKS = {"NONE","MISTAKE","WARNING","BEFORE_ACTION","NUMBER_LIST","CAUSE_SOURCE","HABIT","MYTH","CONSEQUENCE","MULTIPLE"}
TITLE_PROMISE_BONDS = {"PASS","FAIL","NOT_APPLICABLE"}


def _promise_sentences(text: str) -> list[str]:
    out=[]
    for raw in text.splitlines():
        line=re.sub(r"^\s*(?:[-*]|\d+[.)]|\|)\s*", "", raw).strip().strip("|")
        if len(line) >= 18 and not line.startswith("#"):
            out.append(re.sub(r"\s+", " ", line))
    return out

def _promise_tokens(text: str) -> set[str]:
    stop={"this","that","with","from","what","when","where","which","your","after","before","about","into","than","then","they","them","their","have","has","will","would","could","should","most","more","some","very","always","really","possible","simple","common","everyday","keep","going","feel","feels","why","how","and","the","for","are","may","not","all"}
    return {w for w in re.findall(r"[a-z]{4,}", _normalize_gate_text(text)) if w not in stop}

def _section_text(text: str, names: tuple[str,...]) -> str:
    chunks=[]
    for name in names:
        m=re.search(rf"(?ims)^##+\s*{re.escape(name)}\s*$\s*(.*?)(?=^##+\s|\Z)", text)
        if m: chunks.append(m.group(1))
    return "\n".join(chunks)

def _promise_lemma(word: str) -> str:
    w=_normalize_gate_text(word).strip()
    if w.endswith("ies") and len(w)>4: return w[:-3]+"y"
    if w.endswith("s") and len(w)>3: return w[:-1]
    return w

_NUMERIC_ROLE_ALIASES={
    "cause":"CAUSE","reason":"CAUSE","source":"SOURCE_ORIGIN","place":"SOURCE_ORIGIN","origin":"SOURCE_ORIGIN",
    "warning":"WARNING_SIGN","sign":"WARNING_SIGN","mistake":"MISTAKE","error":"MISTAKE","myth":"MYTH","habit":"HABIT",
    "exercise":"EXERCISE","movement":"EXERCISE","food":"FOOD","drink":"FOOD",
    "way":"METHOD_ACTION","method":"METHOD_ACTION","step":"METHOD_ACTION","action":"METHOD_ACTION","tip":"METHOD_ACTION",
    "benefit":"BENEFIT","condition":"SAFETY_CONDITION"}

def _semantic_label(text: str) -> str:
    x=re.sub(r"\([^)]*\)"," ",text.lower())
    x=re.sub(r"[^a-z0-9 /+-]+"," ",x)
    x=re.sub(r"\b(?:may|might|can|could|often|sometimes|possible|common|supported|distinct|the|a|an)\b"," ",x)
    return re.sub(r"\s+"," ",x).strip(" -:;,")

def _semantic_key(text: str) -> frozenset[str]:
    out=[]
    for w in re.findall(r"[a-z]{3,}",_semantic_label(text)):
        if w in {"from","with","into","this","that","than","when","where","which","their","there","through","related","associated"}: continue
        if w.endswith("ing") and len(w)>5: w=w[:-3]
        elif w.endswith("ed") and len(w)>4: w=w[:-2]
        elif w.endswith("ies") and len(w)>4: w=w[:-3]+"y"
        elif w.endswith("s") and len(w)>4: w=w[:-1]
        out.append(w)
    return frozenset(out)

def _semantically_same(a: str,b: str) -> bool:
    ka,kb=_semantic_key(a),_semantic_key(b)
    if not ka or not kb: return _semantic_label(a)==_semantic_label(b)
    if ka<=kb or kb<=ka: return True
    def eq(x,y): return x==y or (min(len(x),len(y))>=5 and (x.endswith(y) or y.endswith(x)))
    matched=sum(1 for x in ka if any(eq(x,y) for y in kb))
    small=min(len(ka),len(kb)); union=max(len(ka|kb),1)
    return matched>=1 and (matched/small>=0.67 or matched/union>=0.55)

def _dedupe_semantic(items: list[str]) -> tuple[str,...]:
    out=[]
    for raw in items:
        label=_semantic_label(raw)
        if label and not any(_semantically_same(label,old) for old in out): out.append(label)
    return tuple(out)

def _split_semantic_list(text: str) -> list[str]:
    return [p.strip(" -:;.") for p in re.split(r"\s*[,;]\s*|\s+\bor\b\s+",re.sub(r"\s+"," ",text),flags=re.I) if re.search(r"[A-Za-z]{3,}",p)]

def _derive_semantic_items(sentences: list[str]) -> dict[str,tuple[str,...]]:
    buckets={}
    def add(role,item): buckets.setdefault(role,[]).append(item)
    for s in sentences:
        # Explicit generic category lists, e.g. "Exercises: A, B" or "foods include A, B".
        m=re.search(r"(?i)\b([a-z][a-z -]{2,30}?)\s*(?:include|includes|are|:)\s+(.+)$",s)
        if m:
            role=_NUMERIC_ROLE_ALIASES.get(_promise_lemma(m.group(1).strip().split()[-1]))
            if role:
                for item in _split_semantic_list(m.group(2)): add(role,item)
        # Source/cause maps must expose an actual list, not merely mention the word cause.
        m=re.search(r"(?i)\b(?:may|can|could)\s+(?:come|start|originate)\s+from\s+(.+)$",s)
        if not m:
            m=re.search(r"(?i)\b(?:causes?|sources?|reasons?|contributors?)\s*(?:include|includes|are|:)\s+(.+)$",s)
        if m:
            items=_split_semantic_list(m.group(1))
            if len(items)>=2:
                for item in items: add("CAUSE",item); add("SOURCE_ORIGIN",item)
        m=re.search(r"(?i)\b(?:warning signs?|red flags?|evaluation triggers?)\s*(?:include|includes|are|:)\s+(.+)$",s)
        if m:
            for item in _split_semantic_list(m.group(1)): add("WARNING_SIGN",item)
        if re.search(r"(?i)\b(?:mistake|misconception|common error|wrong assumption|wrong belief|misuse)\b",s): add("MISTAKE",s)
        if re.search(r"(?i)\b(?:habit|behavior|behaviour|routine)\b",s): add("HABIT",s)
        if re.search(r"(?i)\b(?:myth|misconception|wrong belief|wrong assumption)\b",s): add("MYTH",s)
    return {role:_dedupe_semantic(vals) for role,vals in buckets.items()}

def derive_content_promise_inventory(project: Path) -> dict[str, object]:
    """Derive one immutable, current-project-only promise inventory for a title batch."""
    files=("01_topic_validation.md","02_research_sheet.md","13_fact_check_log.md")
    texts=[]
    for name in files:
        path=project/name
        if not path.is_file(): raise ValueError(f"content-promise source missing: {name}")
        texts.append(path.read_text(encoding="utf-8-sig",errors="replace"))
    joined="\n".join(texts); sentences=_promise_sentences(joined)
    primary=_section_text(texts[0],("Core viewer problem","Recommended angle","Normalized senior-health promise","Viewer desire")) or texts[0]
    patterns={
      "MISTAKES": r"\b(?:mistake|misconception|incorrect|wrong assumption|wrong belief|misuse|common error|get wrong|do not assume|should not assume)\b",
      "WARNINGS": r"\b(?:warning|red flag|urgent|prompt medical|medical evaluation|needs? evaluation|should be evaluated|do not ignore|seek (?:care|evaluation)|choking|shortness of breath|chest pain|blood|weight loss)\b",
      "BEFORE_ACTION_FACTS": r"\b(?:before|avoid|when relevant|when suspected|depending on|according to label|clinician-guided|how much|for whom|under what conditions|do not stop|before changing)\b",
      "CAUSES_OR_SOURCES": r"\b(?:cause|causes|source|coming from|contribut|trigger|reason|origin|may come from|can come from)\b",
      "HABITS": r"\b(?:habit|behavior|behaviour|routine|repeated|frequent|constantly|loop)\b",
      "MYTHS": r"\b(?:myth|misconception|incorrect belief|wrong belief|wrong assumption|not always|does not mean|do not assume)\b",
      "CONSEQUENCES": r"\b(?:worsen|worsening|consequence|lead to|risk of|delay.*care|aspiration|fall|confusion|complication)\b",
    }
    cats={k:tuple(s for s in sentences if re.search(p,s,re.I)) for k,p in patterns.items()}
    semantic_sections=[]
    section_names=("Research Summary","Approved Angle From Validation","Approved Claims","Claims Requiring Careful Wording","Approved Framing","Next Agent Input Summary","Core viewer problem","Recommended angle","Normalized senior-health promise","Viewer desire")
    for text in texts:
        selected=_section_text(text,section_names)
        if selected: semantic_sections.append(selected)
    semantic_sentences=[]
    for line in _promise_sentences("\n".join(semantic_sections)):
        semantic_sentences.extend(x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z])",line) if len(x.strip())>=18)
    semantic=_derive_semantic_items(semantic_sentences)
    return {"source_files":files,"source_reads":3,"source_digest":hashlib.sha256(joined.encode()).hexdigest(),
            "PRIMARY_PROMISE":primary,"PRIMARY_TOKENS":frozenset(_promise_tokens(primary)),
            **cats,"SEMANTIC_ITEMS":semantic,"ALL_TEXT":joined}

def _extract_numeric_promise(title: str) -> tuple[int|None,str|None,str|None]:
    text=title.lower()
    pat=r"\b(\d+)\s+(?:(?:possible|common|likely|main|best|simple|daily)\s+)?([a-z][a-z-]{2,24})\b"
    stop_nouns={"and","but","with","when","after","before","year","years","old"}
    for m in re.finditer(pat,text):
        prefix=text[max(0,m.start()-12):m.start()]
        if re.search(r"\b(?:over|after|age|aged)\s*$",prefix):
            continue
        noun=_promise_lemma(m.group(2))
        if noun in stop_nouns:
            continue
        return int(m.group(1)),noun,_NUMERIC_ROLE_ALIASES.get(noun)
    return None,None,None

def detect_content_promise_hook(title: str) -> tuple[str, int|None, str|None]:
    low=_normalize_gate_text(title); hooks=[]; count=None; underlying=None
    count,noun,role=_extract_numeric_promise(title)
    if count is not None:
        hooks.append("NUMBER_LIST")
        underlying=("MISTAKE" if role=="MISTAKE" else "WARNING" if role=="WARNING_SIGN" else "HABIT" if role=="HABIT" else "MYTH" if role=="MYTH" else "CAUSE_SOURCE" if role in {"CAUSE","SOURCE_ORIGIN"} else None)
    checks=(("MISTAKE",r"\b(?:mistake|common error|wrong assumption)\b"),("WARNING",r"\b(?:warning signs?|red flags?|don t ignore|do not ignore|watch for|needs? a closer look|get it checked|should be checked)\b"),("BEFORE_ACTION",r"\b(?:before you|read this first|watch this first|before taking|before drinking|before eating|before using|what to check first|what to try first)\b"),("CAUSE_SOURCE",r"\b(?:causes?|places? it may|real source|where it (?:comes|may come) from|coming from|why (?:it|this|that) happens|why you|why your|nose,? stomach,? or something else)\b"),("HABIT",r"\b(?:habit|routine)\b"),("MYTH",r"\b(?:myth|what (?:people|seniors) get wrong)\b"),("CONSEQUENCE",r"\b(?:you ll regret|you will regret|before it gets worse|what happens if|gets worse|worsening)\b"))
    for hook,pat in checks:
        if re.search(pat,low) and hook not in hooks: hooks.append(hook)
    # Generic "why" is ordinary explainer framing unless it explicitly promises cause/source structure.
    if "CAUSE_SOURCE" in hooks and re.search(r"\bwhy (?:you|your)\b",low) and not re.search(r"\b(?:cause|source|coming from|comes from|happens)\b",low): hooks.remove("CAUSE_SOURCE")
    if not hooks:return "NONE",None,None
    return (hooks[0] if len(hooks)==1 else "MULTIPLE"),count,underlying

def _promise_relevant(title: str, evidence: str, inventory: dict[str,object]) -> bool:
    tt=_promise_tokens(title); et=_promise_tokens(evidence); pt=set(inventory["PRIMARY_TOKENS"])
    return bool(tt & et) and bool((tt & pt) or (et & pt))

def evaluate_content_promise(title: str, inventory: dict[str,object]) -> tuple[str,str,str]:
    hook,count,underlying=detect_content_promise_hook(title)
    if hook=="NONE": return hook,"NOT_APPLICABLE","No special content-promise hook detected in title structure."
    needed=[]
    if hook=="MULTIPLE":
        low=_normalize_gate_text(title)
        for h,p in (("MISTAKE",r"mistake"),("WARNING",r"warning|red flag|ignore"),("BEFORE_ACTION",r"before|first"),("CAUSE_SOURCE",r"cause|source|coming from|comes from"),("HABIT",r"habit|routine"),("MYTH",r"myth|get wrong"),("CONSEQUENCE",r"regret|gets worse|what happens if")):
            if re.search(p,low): needed.append(h)
        if count is not None: needed.insert(0,"NUMBER_LIST")
    else: needed=[hook]
    reasons=[]
    for h in needed:
        base=underlying if h=="NUMBER_LIST" and underlying else h
        cat={"MISTAKE":"MISTAKES","WARNING":"WARNINGS","BEFORE_ACTION":"BEFORE_ACTION_FACTS","CAUSE_SOURCE":"CAUSES_OR_SOURCES","HABIT":"HABITS","MYTH":"MYTHS","CONSEQUENCE":"CONSEQUENCES"}.get(base)
        evidence=list(inventory.get(cat,())) if cat else []
        relevant=[e for e in evidence if _promise_relevant(title,e,inventory)]
        if h=="NUMBER_LIST":
            parsed_count,noun,role=_extract_numeric_promise(title)
            if count is None or role is None:
                return hook,"FAIL",f"NUMBER_LIST_UNRESOLVED_CATEGORY: required={count}; category={noun or 'UNKNOWN'}; distinct_supported=0; result=FAIL"
            items=tuple(inventory.get("SEMANTIC_ITEMS",{}).get(role,()))
            distinct=len(items); result="PASS" if distinct>=count else "FAIL"
            labels=", ".join(items[:8])
            diag=f"NUMBER_LIST: required={count}; category={role}; distinct_supported={distinct}; result={result}" + (f"; concepts=[{labels}]" if labels else "")
            if result=="FAIL": return hook,"FAIL",diag
            reasons.append(diag)
        elif not relevant:
            return hook,"FAIL",f"{base} promise lacks meaningful current-project evidence materially connected to the primary promise."
        else:
            reasons.append(f"{base} supported by current-project evidence: {relevant[0][:180]}")
    return hook,"PASS","; ".join(reasons)

def classify_content_promises(rows: list[dict[str,str]], project: Path) -> tuple[list[dict[str,object]],dict[str,object]]:
    inventory=derive_content_promise_inventory(project)
    results=[]
    for row in rows:
        hook,bond,reason=evaluate_content_promise(row.get("title",""),inventory)
        results.append({"row":row,"promise_hook":hook,"content_promise_bond":bond,"content_promise_reason":reason})
    return results,inventory

def _strict_int(value: str, low: int, high: int) -> int | None:
    if not re.fullmatch(r"-?\d+", (value or "").strip()):
        return None
    number = int(value)
    return number if low <= number <= high else None

def _md_selection(md: str, heading: str) -> str | None:
    m = re.search(rf"(?ims)^##+\s*{re.escape(heading)}\s*$\s*(.*?)(?=^##+\s|\Z)", md)
    if not m:
        return None
    block = m.group(1)
    title = re.search(r"(?im)^(?:Title|Recommended winner|Safest high-CTR alternative|Highest-upside experiment)\s*:\s*(.+?)\s*$", block)
    if title:
        return title.group(1).strip().strip('*')
    for line in block.splitlines():
        line=line.strip().strip('*')
        if line and not line.startswith(('#','-','|')):
            return line
    return None

def _md_final_selection(md: str, label: str) -> str | None:
    m = re.search(r"(?ims)^##+\s*Final Selections\s*$\s*(.*?)(?=^##+\s|\Z)", md)
    if not m:
        return None
    found = re.search(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", m.group(1))
    return found.group(1).strip().strip('*') if found else None




PACKAGING_CLINICAL_PHRASES = (
    "normal function", "healthy function", "mechanism of action",
    "what research shows", "what science says", "evidence suggests",
)
PACKAGING_QUALIFIERS = ("may", "might", "could", "potentially", "possibly", "suggests", "appears to")


def objective_packaging_signals(title: str) -> dict[str, object]:
    """Conservative, topic-neutral diagnostics for obvious packaging weakness.

    These signals are NOT Medical Gate checks and are NOT A/B/C gates.  They never
    make a title medically safe and never create anchor_variation=YES.
    """
    low=_normalize_gate_text(title or "")
    words=low.split()
    qualifier_count=sum(1 for q in PACKAGING_QUALIFIERS if re.search(rf"\b{re.escape(q)}\b", low))
    clinical_hits=[p for p in PACKAGING_CLINICAL_PHRASES if p.replace("-"," ") in low]
    question=bool("?" in (title or ""))
    action=bool(re.search(r"\b(?:eat|drink|add|try|stop|avoid|walk|stand|sit|do|take|use|check|ask|choose|swap|start|skip)\b", low))
    contrast=bool(re.search(r"\b(?:but|vs|versus|instead|before|after|can(?:not|'t)|mistake|wrong|right)\b", low))
    human_problem=bool(re.search(r"\b(?:heavy|weak|dry|tired|pain|balance|sleep|walking|walk|legs?|feet|skin|breakfast|water|coffee|meal|chair|stairs?)\b", low))
    mechanism_only=bool(clinical_hits) and not (question or action or contrast or human_problem)
    excessive_qualifiers=qualifier_count >= 2
    high_clinical_density=bool(words) and (sum(len(p.split()) for p in clinical_hits) / max(1,len(words)) >= 0.30)
    generic_educational=bool(re.search(r"\b(?:explained|overview|guide to|understanding)\b", low)) and not (question or action or contrast or human_problem)
    weak=excessive_qualifiers or (mechanism_only and high_clinical_density) or generic_educational
    return {
        "excessive_qualifier_stacking": excessive_qualifiers,
        "clinical_phrase_hits": tuple(clinical_hits),
        "high_clinical_density": high_clinical_density,
        "mechanism_only": mechanism_only,
        "generic_educational_framing": generic_educational,
        "has_concrete_viewer_signal": bool(question or action or contrast or human_problem),
        "objective_packaging_weak": weak,
    }


def objective_packaging_validation(title: str) -> tuple[str, str]:
    """Return STRONG-CANDIDATE or WEAK without acting as a medical/anchor gate."""
    s=objective_packaging_signals(title)
    if not s["objective_packaging_weak"]:
        return "STRONG-CANDIDATE", "no objective weak-packaging structure detected"
    reasons=[]
    if s["excessive_qualifier_stacking"]: reasons.append("qualifier stacking")
    if s["mechanism_only"] and s["high_clinical_density"]: reasons.append("mechanism-only clinical density")
    if s["generic_educational_framing"]: reasons.append("generic educational framing")
    return "WEAK", ", ".join(reasons)

def _title_score(row: dict[str, str]) -> int | None:
    fields = ("consensus_fit", "medical_safety", "audience_fit", "viewer_benefit",
              "viewer_curiosity_weighted", "search_intent_score", "thumbnail_compatibility", "novelty", "clarity")
    limits = {"consensus_fit":15,"medical_safety":15,"audience_fit":10,"viewer_benefit":15,
              "viewer_curiosity_weighted":15,"search_intent_score":10,"thumbnail_compatibility":10,"novelty":5,"clarity":5}
    vals=[]
    for field in fields:
        value=_strict_int(row.get(field, ""), 0, limits[field])
        if value is None:
            return None
        vals.append(value)
    return sum(vals)

def title_publish_recommendation(row: dict[str, str]) -> str:
    """Single deterministic V2 publish decision table. Risk is the medical-safety override."""
    score=_strict_int(row.get("overall_score", ""), 0, 100)
    risk=(row.get("risk_level") or "").strip().upper()
    experimental=(row.get("experimental") or "").strip().upper()=="YES"
    if score is None or risk not in {"LOW","MEDIUM","HIGH"}:
        return "HOLD"
    if risk == "HIGH" or score < 86:
        return "HOLD"
    if experimental or risk == "MEDIUM":
        return "TEST"
    if score >= 92:
        return "PRIORITY"
    return "STRONG"

def _title_ranking_key(row: dict[str, str], original_index: int) -> tuple:
    """Authoritative deterministic ranking: score first, then the explicit V2 tie chain."""
    risk_order={"LOW":0,"MEDIUM":1,"HIGH":2}
    def n(field: str, high: int=100) -> int:
        value=_strict_int(row.get(field, ""), 0, high)
        return value if value is not None else -1
    return (-n("overall_score"), -n("medical_safety",15), -n("viewer_benefit",15),
            -n("consensus_fit",15), -n("audience_fit",10), -n("packaging_confidence"),
            risk_order.get((row.get("risk_level") or "").strip().upper(),99),
            -n("viewer_curiosity_weighted",15), -n("search_intent_score",10),
            -n("thumbnail_compatibility",10), original_index)

def derive_anchor_skeleton(anchor: str) -> str:
    """Derive a structural, claim-neutral skeleton from the supplied wording; never copy its medical claim as a requirement."""
    text=(anchor or "").strip()
    if not text:
        return ""
    m=re.match(r"^(.*?:\s*)The\s+(.+?)\s+That\s+(.+)$", text, flags=re.I)
    if m:
        return f"{m.group(1)}The [Subject] That [Safe Support Statement]"
    m=re.match(r"^(.*?:\s*)(.+)$", text)
    if m:
        return f"{m.group(1)}[Research-Approved Structural Variation]"
    return "[Research-Approved Structural Variation]"


def _anchor_original_claim(anchor: str) -> str:
    """Return only the claim-bearing tail of the supplied anchor, preserving its text."""
    text=(anchor or "").strip()
    m=re.search(r"\bThat\s+(.+)$", text, flags=re.I)
    return m.group(1).strip() if m else text

def _anchor_gate_reason(project: Path, anchor: str) -> str:
    """Use the project's Medical Gate 1 evidence for the adjustment reason when available."""
    fact=project/"13_fact_check_log.md"
    if fact.is_file():
        text=fact.read_text(encoding="utf-8-sig", errors="replace")
        claim_terms=[t.lower() for t in re.findall(r"[A-Za-z]{4,}", _anchor_original_claim(anchor))]
        priority=("circulation","vein","vascular","unsupported","prohibited","claim","support")
        lines=[re.sub(r"\s+"," ",ln.strip(" -*\t")) for ln in text.splitlines() if ln.strip()]
        candidates=[]
        for ln in lines:
            low=ln.lower()
            overlap=sum(term in low for term in claim_terms)
            signal=sum(term in low for term in priority)
            if overlap and signal:
                candidates.append((overlap+signal,ln))
        if candidates:
            return max(candidates,key=lambda x:x[0])[1][:500]
    return "Medical Gate 1 does not authorize the supplied benefit claim as written; only research-approved support wording may be retained."

@dataclass(frozen=True)
class DerivedGateTerm:
    normalized_term: str
    source: str
    source_span: str
    source_text: str
    start: int
    end: int
    derivation: str = "literal"


class AnchorVocabularyLeak(Exception):
    """Internal deterministic validation signal; callers must convert it to a controlled FAIL."""
    def __init__(self, term: DerivedGateTerm, reason: str, diagnostics: list[dict[str, object]] | None = None):
        self.term = term
        self.reason = reason
        self.diagnostics = list(diagnostics or [])
        super().__init__(f"cross-project anchor vocabulary leak: {term.normalized_term}: {reason}")


def _anchor_source_texts(project: Path | None, anchor: str) -> list[tuple[str, str]]:
    """Return only current-run sources authorized to define anchor vocabulary."""
    sources=[("anchor", (anchor or "").strip())]
    if project is not None:
        for filename,label in (("02_research_sheet.md","research"),
                               ("13_fact_check_log.md","medical_gate")):
            path=project/filename
            if path.is_file():
                sources.append((label,path.read_text(encoding="utf-8-sig", errors="replace")))
    return sources


def _normalize_gate_text(text: str) -> str:
    """Topic-neutral normalization used by both derivation and provenance validation."""
    text=(text or "").casefold().replace("-", " ").replace("—", " ").replace("–", " ")
    text=re.sub(r"[^a-z0-9+\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _token_base(token: str) -> str:
    """Conservative topic-neutral singular/plural normalization; never maps concepts to synonyms."""
    t=(token or "").casefold()
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 4 and t.endswith("es") and not t.endswith(("ses", "xes", "zes")):
        return t[:-1]
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _normalized_equivalent(a: str, b: str) -> bool:
    na,nb=_normalize_gate_text(a),_normalize_gate_text(b)
    if na == nb:
        return True
    ta=[_token_base(x) for x in na.split()]
    tb=[_token_base(x) for x in nb.split()]
    return bool(ta and ta == tb)


def _source_span_for_term(source_type: str, source_text: str, term: str) -> DerivedGateTerm | None:
    """Find a current-source span supporting a normalized derivative without requiring literal identity."""
    norm_term=_normalize_gate_text(term)
    if not norm_term:
        return None
    # First prefer a direct case/punctuation/hyphen-insensitive line span.
    offset=0
    for raw_line in source_text.splitlines(True) or [source_text]:
        line=raw_line.rstrip("\r\n")
        norm_line=_normalize_gate_text(line)
        if norm_term in norm_line:
            return DerivedGateTerm(norm_term,source_type,line,source_text,offset,offset+len(line),"normalized source span")
        # Then allow only topic-neutral singular/plural normalization on tokens from this exact line.
        term_tokens=[_token_base(x) for x in norm_term.split()]
        line_tokens=[_token_base(x) for x in norm_line.split()]
        if term_tokens and any(line_tokens[i:i+len(term_tokens)] == term_tokens for i in range(max(0,len(line_tokens)-len(term_tokens)+1))):
            return DerivedGateTerm(norm_term,source_type,line,source_text,offset,offset+len(line),"source-backed singular/plural normalization")
        offset += len(raw_line)
    return None


def _anchor_terms(text: str) -> list[str]:
    """Tokenize source text without embedding any topic-specific vocabulary."""
    return [_normalize_gate_text(m.group(0)) for m in re.finditer(r"[A-Za-z][A-Za-z'-]{2,}", text or "")]


def _anchor_content_terms(text: str) -> set[str]:
    # Language glue/action words only. This list is intentionally topic-neutral.
    stop={
        "the","and","for","with","from","into","that","this","these","those","your","you","our","their",
        "what","why","how","when","where","who","which","about","after","before","over","under","than",
        "are","was","were","been","being","have","has","had","does","did","can","could","may","might",
        "will","would","should","must","not","but","only","also","more","most","less","very","just",
        "stop","start","add","use","using","used","look","looking","looks","see","know","need","needs",
        "support","supports","supporting","supported","help","helps","helping","helped","discuss","promise","promises",
        "here","heres","actually","plain","daily","every","one","thing","things","way","ways",
        "some","older","adult","adults","senior","seniors",
    }
    return {t for t in _anchor_terms(text) if t not in stop and len(t) >= 3}


def _anchor_clause_seeds(anchor: str) -> tuple[set[str], set[str]]:
    """Split the supplied anchor into subject-lane and payoff-lane seed terms."""
    body=(anchor or "").split(":",1)[-1].strip()
    matches=list(re.finditer(r"\b(?:that|for|so|because)\b", body, flags=re.I))
    if matches:
        m=matches[-1]
        left,right=body[:m.start()],body[m.end():]
    else:
        parts=[x.strip() for x in re.split(r"[!?;—]+", body) if x.strip()]
        left=parts[0] if parts else body
        right=" ".join(parts[1:]) if len(parts)>1 else body
    return _anchor_content_terms(left), _anchor_content_terms(right)


def _record_term(out: dict[str, DerivedGateTerm], term: str, sources: list[tuple[str,str]], preferred_source: str | None = None) -> None:
    norm=_normalize_gate_text(term)
    if not norm or norm in out:
        return
    ordered=sorted(sources,key=lambda x: 0 if preferred_source and x[0]==preferred_source else 1)
    for source_type,source_text in ordered:
        proof=_source_span_for_term(source_type,source_text,norm)
        if proof:
            out[norm]=proof
            return
    # Keep the unproven term so the guard can deterministically identify the exact injection.
    out[norm]=DerivedGateTerm(norm,preferred_source or "unknown","","",-1,-1,"no current-project provenance")


def _expand_anchor_lane(seed: set[str], blocked: set[str], sources: list[tuple[str,str]]) -> dict[str, DerivedGateTerm]:
    """Expand the WHAT lane only with explicit current-project subject aliases/refinements.

    This intentionally does not promote arbitrary nouns that merely co-occur with the
    anchor subject in Research/Medical Gate.  Subject expansion is limited to forms
    that explicitly refine the anchor subject (for example a one-token subtype such
    as ``X C``) or an explicit source statement that identifies an alias/related
    subject.  This preserves semantic-role provenance instead of plain word provenance.
    """
    provenance: dict[str,DerivedGateTerm]={}
    for term in seed:
        _record_term(provenance,term,sources,preferred_source="anchor")
    if not seed:
        return provenance

    norm_seeds={_normalize_gate_text(x) for x in seed if _normalize_gate_text(x)}
    for label,text in sources:
        if label == "anchor":
            continue
        for raw_line in text.splitlines() or [text]:
            line=re.sub(r"\s+"," ",raw_line.strip())
            norm=_normalize_gate_text(line)
            if not line or not any(re.search(rf"\b{re.escape(x)}\b",norm) for x in norm_seeds):
                continue

            # Explicit mystery-subject declaration, e.g. "Use X as the mystery Y".
            for m in re.finditer(r"\buse\s+([a-z0-9 ]{1,40}?)\s+as\s+(?:the\s+)?mystery\s+([a-z0-9 ]{1,30}?)(?:\s+but\b|$)", norm):
                alias=_normalize_gate_text(m.group(1))
                target=_normalize_gate_text(m.group(2))
                if alias and any(re.search(rf"\b{re.escape(x)}\b",target) for x in norm_seeds):
                    if not any(b and re.search(rf"\b{re.escape(b)}\b",alias) for b in blocked):
                        _record_term(provenance,alias,sources,preferred_source=label)

            # Explicit source relation "X and Y are related" may refine the same
            # central subject lane.  This is deliberately narrow and does not use
            # ordinary co-occurrence as synonymy.
            m=re.search(r"\b([a-z0-9 ]{1,35}?)\s+and\s+([a-z0-9 ]{1,35}?)\s+(?:are|is)\s+related\b", norm)
            if m:
                left,right=(_normalize_gate_text(m.group(1)),_normalize_gate_text(m.group(2)))
                sides=((left,right),(right,left))
                for known,alias in sides:
                    if any(re.search(rf"\b{re.escape(x)}\b",known) for x in norm_seeds):
                        alias_tokens=[t for t in alias.split() if t not in {"intake","routine","practice"}]
                        alias=" ".join(alias_tokens[-3:])
                        if alias and alias not in blocked:
                            _record_term(provenance,alias,sources,preferred_source=label)
    return provenance


def _approved_medical_fragments(fact_text: str) -> list[str]:
    """Extract positive Medical Gate wording without importing rejected/cautionary lanes."""
    fragments=[]
    section=""
    for raw in (fact_text or "").splitlines():
        stripped=raw.strip()
        if stripped.startswith("##"):
            section=_normalize_gate_text(stripped.lstrip("# "))
            continue
        if not stripped:
            continue

        # Claim tables: use only the Approved Wording cell for approved decisions.
        if stripped.startswith("|"):
            cells=[c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) >= 3:
                decision=_normalize_gate_text(cells[1])
                if decision.startswith("approved"):
                    fragments.append(cells[2])
            continue

        low=_normalize_gate_text(stripped)
        if section == "approved claims" and re.match(r"^\d+[.)]\s*", stripped):
            fragments.append(re.sub(r"^\d+[.)]\s*", "", stripped))
            continue
        for marker in (
            "safe replacement framing", "approved research promise",
            "approved framing", "approved packaging boundary",
            "keep the promise narrow",
        ):
            pos=low.find(marker)
            if pos >= 0:
                # Slice the original text at the corresponding colon; normalization is
                # used only to detect the semantic-role marker.
                colon=stripped.find(":")
                fragment=stripped[colon+1:].strip() if colon >= 0 else stripped
                fragments.append(fragment)
                break
    return fragments


def _clean_concept_phrase(text: str) -> str:
    words=_normalize_gate_text(text).split()
    leading={
        "a","an","the","normal","healthy","adequate","enough","one","part","of",
        "senior","seniors","older","adult","adults","your","our","getting","required",
        "needed","use","using","approved","framing","boundary","promise","narrow","which",
        "is","are","can","may","will","to","make","for","support","supports","supported","supporting","help","helps","surrounding",
    }
    trailing={"as","one","factor","especially","biology","where","medically","appropriate"}
    while words and words[0] in leading:
        words.pop(0)
    while words and words[-1] in trailing:
        words.pop()
    return " ".join(words[:6]).strip()


def _payoff_phrase_variants(phrase: str) -> tuple[set[str],set[str]]:
    """Return relational objects and direct role-bearing payoff phrases."""
    p=_clean_concept_phrase(phrase)
    if not p:
        return set(),set()
    toks=p.split()
    role_heads={"formation","structure","health","comfort","integrity","function","strength","mobility","balance","steadiness","stability","independence","hydration"}
    objects=set()
    direct=set()
    if toks[-1] in role_heads and len(toks) >= 2:
        direct.add(p)
        base=" ".join(toks[:-1]).strip()
        if base:
            objects.add(base)
    else:
        objects.add(p)
    return objects,direct


def _derive_payoff_lane(sources: list[tuple[str,str]], blocked: set[str]) -> tuple[dict[str,DerivedGateTerm],dict[str,DerivedGateTerm]]:
    """Derive WHY/PAYOFF concepts from positive Medical Gate semantic-role evidence.

    The extractor recognizes approved support relations and role-bearing payoff noun
    phrases.  It never turns the standalone word ``support`` or arbitrary words from
    Research into Gate C vocabulary.
    """
    fact_text=next((text for label,text in sources if label=="medical_gate"),"")
    objects: dict[str,DerivedGateTerm]={}
    direct: dict[str,DerivedGateTerm]={}

    def record(target: dict[str,DerivedGateTerm], term: str) -> None:
        term=_clean_concept_phrase(term)
        if not term or term in blocked:
            return
        # Derived forms are accepted only when the normalized phrase itself is
        # reproducible from an authorized current-project source span.
        if not any(_source_span_for_term(label,text,term) is not None for label,text in sources):
            return
        _record_term(target,term,sources,preferred_source="medical_gate")

    def add_phrase(phrase: str, *, direct_hint: bool=False) -> None:
        obj,dir_terms=_payoff_phrase_variants(phrase)
        # direct_hint is retained for call-site clarity; relational base objects
        # never become direct matches merely because they precede the word support.
        for term in obj:
            record(objects,term)
        for term in dir_terms:
            record(direct,term)

    role_heads=("formation","structure","health","comfort","integrity","function","strength","mobility","balance","steadiness","stability","independence")

    for fragment in _approved_medical_fragments(fact_text):
        # Preserve comma/semicolon boundaries because they separate approved concept
        # groups (for example packaging-boundary lists).
        positive=re.split(r"(?i)\b(?:do not|don't|avoid|but)\b", fragment, maxsplit=1)[0]
        for raw_clause in re.split(r"[,;]", positive):
            clause=_normalize_gate_text(raw_clause)
            if not clause:
                continue

            # Verb relation: X [helps] support(s) Y.
            for m in re.finditer(r"\b(?:(help(?:s|ed|ing)?)\s+)?support(?:s|ed|ing)?\s+(.+)$", clause):
                before=clause[:m.start()].strip()
                if before.split()[-1:] == ["better"]:
                    continue
                tail=m.group(2).strip()
                # Stop at explanatory connectors; each side is independently source-backed.
                for part in re.split(r"\b(?:for|through|which|that|as|and)\b", tail):
                    part=_clean_concept_phrase(part)
                    if part:
                        add_phrase(part)
                # Approved mechanism nouns immediately before "help support" belong to
                # WHY as relational objects, not to WHAT.
                if m.group(1):
                    prefix=re.split(r"[:.]",before)[-1]
                    prefix=re.sub(r"\b(?:getting|enough|required|needed|can|may|will|does|is|are|be|to)\b", " ", prefix)
                    for part in re.split(r"\band\b", prefix):
                        words=_clean_concept_phrase(part).split()
                        if 1 <= len(words) <= 4:
                            add_phrase(" ".join(words))

            # Noun relation: X support / X structural support.  Split coordinated
            # concepts so "collagen and blood-vessel structure support" contributes
            # collagen + blood-vessel structure, not one giant word bag.
            for m in re.finditer(r"\b(.+?)\s+(?:structural\s+)?support$", clause):
                prefix=re.split(r"[:.]",m.group(1))[-1]
                for part in re.split(r"\band\b", prefix):
                    words=_clean_concept_phrase(part).split()
                    if not words:
                        continue
                    phrase=" ".join(words[-4:])
                    add_phrase(phrase, direct_hint=bool(words[-1] in role_heads))

            # Approved direct payoff phrases such as "collagen formation",
            # "blood-vessel structure", or "dry-skin comfort" may appear without an
            # explicit support verb in a title.  Extract only a compact phrase ending
            # in a semantic payoff head; never add the head word by itself.
            words=clause.split()
            boundary_words={"support","supports","supported","supporting","help","helps","helped","helping","for","to","of","and","which","is","are"}
            for i,word in enumerate(words):
                if word not in role_heads:
                    continue
                boundary=-1
                for j in range(i-1,max(-1,i-4),-1):
                    if words[j] in boundary_words:
                        boundary=j
                        break
                # Prefer compact 2-3 token source-backed payoff phrases.
                left=max(boundary+1,i-2)
                phrase=_clean_concept_phrase(" ".join(words[left:i+1]))
                if len(phrase.split()) >= 2:
                    add_phrase(phrase)

    return objects,direct


def _add_compatible_anchor_payoff_targets(anchor: str, sources: list[tuple[str,str]],
                                          c_terms: dict[str,DerivedGateTerm],
                                          c_direct: dict[str,DerivedGateTerm]) -> None:
    """Add conservative anchor target phrases to C only when Medical Gate is compatible.

    These targets remain relational objects: their bare presence never passes Gate C.
    This supports project-generic constructions such as "support <anchor anatomy/target>"
    while preventing rejected anchor promises from becoming positive payoff concepts.
    """
    if not (c_terms or c_direct):
        return
    body=(anchor or "").split(":",1)[-1].strip()
    matches=list(re.finditer(r"\b(?:that|for|so|because)\b", body, flags=re.I))
    right=body[matches[-1].end():] if matches else body
    fact_text=next((text for label,text in sources if label=="medical_gate"),"")
    positive="\n".join(_approved_medical_fragments(fact_text))
    pos_norm=_normalize_gate_text(positive)
    negative_lines=[_normalize_gate_text(x) for x in fact_text.splitlines()
                    if re.search(r"(?i)\b(?:do not|don't|must not|avoid|rejected|unsupported|does not prove|not a treatment|not prove)\b", x)]
    relation_words={"support","supports","supported","supporting","help","helps","helped","helping","for","with","through"}
    modifiers={"healthy","healthier","normal","better","improved","improving","the","a","an","your","our","this","that"}
    for raw_part in re.split(r"[&,;/]", right):
        words=_normalize_gate_text(raw_part).split()
        while words and words[0] in relation_words | modifiers:
            words.pop(0)
        if len(words) < 2:
            continue
        candidate=" ".join(words[-4:])
        cand_tokens=[_token_base(x) for x in candidate.split()]
        if len(cand_tokens) < 2:
            continue
        positive_exact=any(
            [_token_base(x) for x in _normalize_gate_text(candidate).split()] ==
            [_token_base(x) for x in _normalize_gate_text(chunk).split()]
            for chunk in re.findall(r"[A-Za-z0-9][A-Za-z0-9 -]{2,}", positive)
        ) or _normalize_gate_text(candidate) in pos_norm
        rejected=False
        if not positive_exact:
            for neg in negative_lines:
                neg_tokens={_token_base(x) for x in neg.split()}
                if sum(tok in neg_tokens for tok in cand_tokens) >= 2:
                    rejected=True
                    break
        if rejected:
            continue
        # Candidate must itself be traceable to the runtime anchor.  It is added only
        # as a relational C object; _payoff_gate_matches still requires support/help.
        if _source_span_for_term("anchor", sources[0][1], candidate) is not None:
            _record_term(c_terms,candidate,sources,preferred_source="anchor")


def _payoff_gate_matches(low_title: str, gates: dict[str,object]) -> bool:
    """Match WHY while requiring payoff content, not the standalone support verb."""
    normalized=_normalize_gate_text(low_title)
    direct=gates.get("C_direct",{})
    if direct and _gate_matches(normalized,direct):
        return True
    relation=bool(re.search(r"\b(?:support|supports|supported|supporting|help|helps|helped|helping)\b", normalized))
    return bool(relation and _gate_matches(normalized,gates.get("C",{})))

def _validate_gate_provenance(term: DerivedGateTerm, sources: list[tuple[str,str]]) -> tuple[bool,str]:
    authorized={"anchor","research","medical_gate"}
    if term.source not in authorized:
        return False, f"source type {term.source!r} is not an authorized current-project source"
    source_text=next((text for label,text in sources if label==term.source),None)
    if source_text is None:
        return False, f"source {term.source!r} is absent from this project's runtime sources"
    if term.source_text != source_text:
        return False, "provenance source_text does not equal the current project's source text"
    if term.start < 0 or term.end < term.start or source_text[term.start:term.end] != term.source_span:
        return False, "provenance source_span is not an exact span of the current project's source text"
    proof=_source_span_for_term(term.source,source_text,term.normalized_term)
    if proof is None:
        return False, "normalized derivative cannot be reproduced from its claimed current-project source span"
    if not (_normalized_equivalent(term.normalized_term,proof.normalized_term) or _normalize_gate_text(term.normalized_term) in _normalize_gate_text(term.source_span)):
        return False, "normalized derivative is not traceable by allowed topic-neutral normalization"
    return True, f"accepted from {term.source} via {term.derivation}; exact span belongs to current project"


def _public_gate_map(terms: dict[str, DerivedGateTerm]) -> dict[str,set[str]]:
    return {term:{proof.source} for term,proof in terms.items()}


def build_project_anchor_gates(project: Path | None, anchor: str) -> dict[str, object]:
    """Build A/B/C gate vocabulary from this run's anchor, research, and Medical Gate only."""
    sources=_anchor_source_texts(project,anchor)
    subject_seed,payoff_seed=_anchor_clause_seeds(anchor)

    # Gate A is audience/age ONLY and is derived from the runtime anchor itself.
    # Do not scan research/Medical Gate or arbitrary anchor words: for anchors without
    # a colon, treating the whole anchor as an "audience prefix" previously allowed
    # subject words such as neuropathy/feet/legs/exercises to satisfy Gate A.
    audience: dict[str,set[str]]={}
    anchor_norm=_normalize_gate_text(anchor or "")
    age_match=re.search(r"\b(over|after)\s+(\d{2})\+?\b|\b(\d{2})\+\b", anchor_norm)
    if age_match:
        age=age_match.group(2) or age_match.group(3)
        for phrase in (f"over {age}", f"after {age}", f"{age}+", age):
            audience.setdefault(phrase,set()).add("anchor / derived audience syntax")
        for phrase in ("older adult","older adults","senior","seniors"):
            audience.setdefault(phrase,set()).add("anchor / derived audience syntax")
    if re.search(r"\bseniors?\b", anchor_norm):
        for phrase in ("senior","seniors","older adult","older adults"):
            audience.setdefault(phrase,set()).add("anchor / derived audience syntax")
    if re.search(r"\bolder adults?\b", anchor_norm):
        for phrase in ("older adult","older adults","senior","seniors"):
            audience.setdefault(phrase,set()).add("anchor / derived audience syntax")

    audience_terms=set(audience)
    b_terms=_expand_anchor_lane(subject_seed,payoff_seed | audience_terms,sources)

    # Gate C is the WHY/PAYOFF lane.  It is derived from positive Medical Gate
    # wording, supported by current-project sources, rather than from a broad bag of
    # nearby Research words.  Anchor payoff words may identify the lane but cannot
    # override Medical Gate role provenance.
    c_terms,c_direct=_derive_payoff_lane(sources,set(b_terms) | audience_terms)
    _add_compatible_anchor_payoff_targets(anchor,sources,c_terms,c_direct)

    diagnostics=[]
    anchor_text=sources[0][1] if sources else ""
    anchor_prefix=(anchor_text.split(":",1)[0] if anchor_text else "")
    for term,labels in audience.items():
        proof=_source_span_for_term("anchor",anchor_text,term)
        if proof is not None:
            diagnostics.append({"gate":"A","term":term,"source":proof.source,"source_span":proof.source_span,
                                "normalized_form":_normalize_gate_text(term),"accepted":True,
                                "reason":"accepted from current runtime anchor via topic-neutral normalization"})
        else:
            diagnostics.append({"gate":"A","term":term,"source":"anchor","source_span":anchor_prefix,
                                "normalized_form":_normalize_gate_text(term),"accepted":True,
                                "reason":"accepted as topic-neutral audience syntax derived from the current anchor age/audience cue"})
    first_rejected=None
    for lane,terms in (("B",b_terms),("C",c_terms),("C",c_direct)):
        for term,proof in terms.items():
            accepted,reason=_validate_gate_provenance(proof,sources)
            diagnostics.append({"gate":lane,"term":term,"source":proof.source,"source_span":proof.source_span,
                                "normalized_form":proof.normalized_term,"accepted":accepted,"reason":reason})
            if not accepted and first_rejected is None:
                first_rejected=(proof,reason)
    if first_rejected:
        raise AnchorVocabularyLeak(*first_rejected, diagnostics=diagnostics)
    return {"A":audience,"B":_public_gate_map(b_terms),"C":_public_gate_map(c_terms),
            "C_direct":_public_gate_map(c_direct),
            "sources":[label for label,_ in sources],
            "provenance":{"B":b_terms,"C":c_terms,"C_direct":c_direct},"diagnostics":diagnostics}

def _gate_matches(low_title: str, concepts: dict[str,set[str]]) -> bool:
    title_tokens=[_token_base(x) for x in _normalize_gate_text(low_title).split()]
    for term in concepts:
        term_tokens=[_token_base(x) for x in _normalize_gate_text(term).split()]
        if term_tokens and any(title_tokens[i:i+len(term_tokens)] == term_tokens
                               for i in range(max(0,len(title_tokens)-len(term_tokens)+1))):
            return True
    return False


def classify_anchor_variation(title: str, anchor: str, anchor_first_marked: bool = False,
                              project: Path | None = None,
                              precomputed_gates: dict[str, object] | None = None,
                              precomputed_gate_error: AnchorVocabularyLeak | None = None) -> tuple[bool, str]:
    """Project-derived deterministic anchor classifier; no fixed topic vocabulary."""
    t=(title or "").strip()
    a=(anchor or "").strip()
    if not t or not a:
        return False, "A=NO; B=NO; C=NO"
    low=re.sub(r"\s+", " ", t.lower().replace("-"," "))
    if precomputed_gate_error is not None:
        return False, f"A=NO; B=NO; C=NO; ISSUE={precomputed_gate_error}"
    try:
        gates=precomputed_gates if precomputed_gates is not None else build_project_anchor_gates(project,a)
    except AnchorVocabularyLeak as exc:
        return False, f"A=NO; B=NO; C=NO; ISSUE={exc}"
    # Gate A is matched from the current project's derived audience/qualifier lane.
    # anchor_first_marked is retained only for legacy generated-title callers; imported TXT titles never use it.
    # Gate A is optional only when the runtime anchor genuinely has no audience cue.
    a_pass=bool((not gates["A"]) or _gate_matches(low,gates["A"]) or anchor_first_marked)
    b_pass=_gate_matches(low,gates["B"])

    treatment_word=bool(re.search(
        r"\b(?:treat|treats|treated|treating|cure|cures|cured|curing|reverse|reverses|reversed|"
        r"heal|heals|healed|healing|fix|fixes|fixed|repair|repairs|repaired|repairing|"
        r"unclog|unclogs|unclogged|unclogging|firm|firms|firmed|firming|tighten|tightens|tightened|tightening|"
        r"restore|restores|restored|restoring)\b|\bprevent(?:s|ed|ing)?\s+(?:blood\s+)?clots?\b", low))
    c_pass=bool(_payoff_gate_matches(low,gates) and not treatment_word)
    matched=a_pass and b_pass and c_pass
    return matched, f"A={'YES' if a_pass else 'NO'}; B={'YES' if b_pass else 'NO'}; C={'YES' if c_pass else 'NO'}"

def classify_anchor_variations(rows: list[dict[str, str]], anchor: str, project: Path | None = None) -> list[dict[str, object]]:
    """Classify a canonical row set once so flags, audit, summaries, and validation share one result list."""
    precomputed_gates=None
    precomputed_gate_error=None
    if (anchor or "").strip() and any((row.get("title", "") or "").strip() for row in rows):
        try:
            precomputed_gates=build_project_anchor_gates(project,(anchor or "").strip())
        except AnchorVocabularyLeak as exc:
            precomputed_gate_error=exc
    results=[]
    for row in rows:
        matched, detail=classify_anchor_variation(
            row.get("title", ""), anchor, project=project,
            precomputed_gates=precomputed_gates, precomputed_gate_error=precomputed_gate_error)
        gates={k.strip():v.strip() for k,v in (piece.split("=",1) for piece in detail.split(";") if "=" in piece)}
        results.append({"row":row, "matched":matched, "A":gates.get("A")=="YES",
                        "B":gates.get("B")=="YES", "C":gates.get("C")=="YES",
                        "issue":gates.get("ISSUE","")})
    return results

def _safe_anchor_replacement(rows: list[dict[str,str]], anchor: str) -> str:
    """Derive a replacement framing from a generated title already classified as structurally anchored."""
    unsafe_terms={"circulation","vein","veins","vascular"}
    for row in rows:
        if row.get("anchor_variation") != "YES":
            continue
        title=(row.get("title") or "").strip()
        tail=re.search(r"\bThat\s+(.+)$", title, flags=re.I)
        candidate=(tail.group(1).strip() if tail else title)
        if candidate and not any(term in candidate.lower() for term in unsafe_terms):
            return candidate
    return "Research-approved support statement from the generated, Medical-Gate-compliant title set"

def _anchor_status_lines(anchor_present: bool, count: int) -> tuple[str,str,str]:
    status="PROVIDED" if anchor_present else "UNAVAILABLE"
    if anchor_present:
        risk=f"Anchor-fidelity risk: {status} — unsafe claim wording is medically adjusted while structural fidelity is preserved."
        minimum=f"Anchor-pattern minimum: {status} — applicable; >=8 required; {count} found; {'PASS' if count >= 8 else 'FAIL'}"
    else:
        risk=f"Anchor-fidelity risk: {status} — no runtime anchor was supplied."
        minimum=f"Anchor-pattern minimum: {status} — not applicable."
    return f"Anchor Outlier Pattern: {status}", risk, minimum

def _replace_md_section(md: str, heading: str, body: str) -> str:
    pat=rf"(?ims)^##+\s*{re.escape(heading)}\s*$.*?(?=^##+\s|\Z)"
    replacement=f"## {heading}\n\n{body.rstrip()}\n\n"
    if re.search(pat, md):
        return re.sub(pat, replacement, md, count=1)
    return md.rstrip()+"\n\n"+replacement

def _replace_unique_md_section(md: str, heading: str, body: str) -> str:
    """Replace all copies of a Markdown section with one canonical serialization."""
    pat=rf"(?ims)^##+\s*{re.escape(heading)}\s*$.*?(?=^##+\s|\Z)"
    matches=list(re.finditer(pat, md))
    replacement=f"## {heading}\n\n{body.rstrip()}\n\n"
    if not matches:
        return md.rstrip()+"\n\n"+replacement
    first_start=matches[0].start()
    without=re.sub(pat, "", md)
    # Preserve the first section's original report position while deleting every stale copy.
    removed_before=sum(m.end()-m.start() for m in matches if m.end() <= first_start)
    insert_at=max(0, first_start-removed_before)
    return without[:insert_at]+replacement+without[insert_at:]

def _canonical_recommendation_records(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    records={}
    for recommendation_type in ("WINNER", "SAFE_ALTERNATIVE", "HIGH_UPSIDE_EXPERIMENT"):
        matches=[row for row in rows if row.get("recommendation_type")==recommendation_type]
        if len(matches) != 1:
            raise ValueError(f"expected exactly one {recommendation_type}; found {len(matches)}")
        records[recommendation_type]=matches[0]
    return records

def _serialize_title_selection_sections(md: str, rows: list[dict[str, str]]) -> str:
    records=_canonical_recommendation_records(rows)
    winner=records["WINNER"]
    safe=records["SAFE_ALTERNATIVE"]
    exp=records["HIGH_UPSIDE_EXPERIMENT"]
    md=_replace_md_section(
        md,
        "Final Selections",
        "\n\n".join((
            f"Recommended winner: {winner['title']}",
            f"Safest high-CTR alternative: {safe['title']}",
            f"Highest-upside experiment: {exp['title']}",
        )),
    )
    md=_replace_md_section(md,"Recommended Winner",f"Title: {winner['title']}")
    md=_replace_md_section(md,"Safest High-CTR Alternative",f"Title: {safe['title']}")
    md=_replace_md_section(md,"Highest-Upside Experiment",f"Title: {exp['title']}")
    return md

def _serialize_title_score_breakdown(rows: list[dict[str, str]]) -> str:
    """Serialize human-readable per-title scoring from the same canonical rows as CSV."""
    blocks=[]
    for row in rows:
        blocks.append(
            f"**Rank {row['rank']} — {row['title']}**\n"
            f"- Title Family: {row['title_family']}\n"
            f"- Packaging Style: {row['packaging_style']}\n"
            f"- Hook Used: {row['hook_used']}\n"
            f"- Anchor Variation: {row['anchor_variation']}\n"
            f"- Target Audience: {row['target_audience']}\n"
            f"- Consensus Fit: {row['consensus_fit']}/15\n"
            f"- Medical Safety: {row['medical_safety']}/15\n"
            f"- Audience Fit: {row['audience_fit']}/10\n"
            f"- Viewer Benefit: {row['viewer_benefit']}/15\n"
            f"- Viewer Curiosity Raw: {row['viewer_curiosity_raw']}/10\n"
            f"- Viewer Curiosity Weighted: {row['viewer_curiosity_weighted']}/15\n"
            f"- Search Intent: {row['search_intent_type']} ({row['search_intent_score']}/10)\n"
            f"- Thumbnail Compatibility: {row['thumbnail_compatibility']}/10\n"
            f"- Novelty: {row['novelty']}/5\n"
            f"- Clarity: {row['clarity']}/5\n"
            f"- Overall Score: {row['overall_score']}/100\n"
            f"- Packaging Confidence: {row['packaging_confidence']}/100\n"
            f"- Risk Level: {row['risk_level']}\n"
            f"- Risk Note: {row['risk_note']}\n"
            f"- Experimental: {row['experimental']}"
        )
    return "\n\n".join(blocks)

def _serialize_anchor_variation_audit(results: list[dict[str, object]]) -> str:
    """Serialize the already-computed authoritative per-title classification list."""
    lines=["| Rank | Anchor Variation | A audience gate | B project subject | C approved payoff | Title |",
           "|---:|---|---|---|---|---|"]
    for result in results:
        row=result["row"]
        lines.append(
            f"| {row['rank']} | {'YES' if result['matched'] else 'NO'} | {'PASS' if result['A'] else 'FAIL'} | "
            f"{'PASS' if result['B'] else 'FAIL'} | {'PASS' if result['C'] else 'FAIL'} | {row['title']} |"
        )
    return "\n".join(lines)

def _md_anchor_breakdown(md: str) -> dict[int, str]:
    """Read canonical Rank -> Anchor Variation values from the MD score breakdown."""
    m=re.search(r"(?ims)^##+\s*Score Breakdown for Every Title\s*$\s*(.*?)(?=^##+\s|\Z)", md)
    if not m:
        return {}
    block=m.group(1)
    out={}
    rank=None
    for line in block.splitlines():
        rm=re.match(r"^\*\*Rank\s+(\d+)\b.*\*\*$", line.strip(), flags=re.I)
        if rm:
            rank=int(rm.group(1)); continue
        am=re.match(r"^\s*[-*]\s*Anchor Variation\s*:\s*(YES|NO)\s*$", line, flags=re.I)
        if am and rank is not None:
            out[rank]=am.group(1).upper()
    return out

def canonicalize_title_v2_artifacts(project: Path, anchor_outlier_pattern: str | None = None) -> list[str]:
    """Turn Codex CSV candidate intelligence into one deterministic canonical title set and serialize both outputs."""
    csv_path, md_path=project/"03_titles.csv", project/"03_titles.md"
    if not csv_path.exists() or not md_path.exists():
        return ["canonicalization requires both 03_titles.csv and 03_titles.md"]
    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as h:
            reader=csv.DictReader(h); rows=list(reader); header=reader.fieldnames or []
    except Exception as exc:
        return [f"cannot parse candidate CSV: {exc}"]
    if header != TITLE_V2_EXACT_HEADER or len(rows) != 15:
        return ["candidate CSV must use exact V2 header and contain exactly 15 rows before canonicalization"]
    errors=[]
    for i,row in enumerate(rows,1):
        raw=_strict_int(row.get("viewer_curiosity_raw",""),0,10)
        if raw is None:
            errors.append(f"row {i}: viewer_curiosity_raw must be integer 0-10"); continue
        row["viewer_curiosity_weighted"]=str(int((Decimal(raw)*Decimal('1.5')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)))
        score=_title_score(row)
        if score is None:
            errors.append(f"row {i}: one or more score components are invalid"); continue
        row["overall_score"]=str(score)
    if errors:
        return errors
    anchor=(anchor_outlier_pattern or "").strip()
    indexed=list(enumerate(rows))
    indexed.sort(key=lambda pair:_title_ranking_key(pair[1],pair[0]))
    rows=[row for _,row in indexed]
    for rank,row in enumerate(rows,1):
        row["rank"]=str(rank); row["finalist"]="YES" if rank<=5 else "NO"; row["recommendation_type"]="FINALIST" if rank<=5 else "STANDARD"
        row["publish_recommendation"]=title_publish_recommendation(row)
    anchor_results=classify_anchor_variations(rows, anchor, project) if anchor else []
    anchor_issues=sorted({str(r.get("issue") or "") for r in anchor_results if r.get("issue")})
    if anchor_issues:
        return anchor_issues
    if anchor:
        for result in anchor_results:
            result["row"]["anchor_variation"]="YES" if result["matched"] else "NO"
    else:
        for row in rows:
            row["anchor_variation"]="NO"
    promise_sources_ready=all((project/name).is_file() for name in ("01_topic_validation.md","02_research_sheet.md","13_fact_check_log.md"))
    if promise_sources_ready:
        promise_results,promise_inventory=classify_content_promises(rows,project)
    else:
        promise_inventory={"source_reads":0}
        promise_results=[{"row":r,"promise_hook":"NONE","content_promise_bond":"NOT_APPLICABLE","content_promise_reason":"Content-Promise sources unavailable in legacy/test fixture."} for r in rows]
    promise_by_id={id(result["row"]):result for result in promise_results}
    eligible=lambda r: promise_by_id[id(r)]["content_promise_bond"] != "FAIL"
    winner=next((r for r in rows if eligible(r)),None)
    if winner is None: errors.append("no Content-Promise-Bond-eligible candidate is available for WINNER")
    if errors: return errors
    winner["recommendation_type"]="WINNER"
    safe=next((r for r in rows if r is not winner and eligible(r) and r.get("risk_level")=="LOW"),None)
    exp=next((r for r in rows if r is not winner and r is not safe and eligible(r) and r.get("experimental")=="YES"),None)
    if safe is None: errors.append("no LOW-risk candidate is available for SAFE_ALTERNATIVE")
    if exp is None: errors.append("no distinct experimental candidate is available for HIGH_UPSIDE_EXPERIMENT")
    if errors: return errors
    safe["recommendation_type"]="SAFE_ALTERNATIVE"
    exp["recommendation_type"]="HIGH_UPSIDE_EXPERIMENT"
    finalists=rows[:5]
    with csv_path.open("w",encoding="utf-8-sig",newline="") as h:
        w=csv.DictWriter(h,fieldnames=TITLE_V2_EXACT_HEADER,extrasaction="ignore",lineterminator="\n"); w.writeheader(); w.writerows(rows)
    md=md_path.read_text(encoding="utf-8-sig")
    anchor=(anchor_outlier_pattern or "").strip()
    count=sum(r.get("anchor_variation")=="YES" for r in rows)
    sm=re.search(r"(?ims)^##+\s*Title Strategy Summary\s*$\s*(.*?)(?=^##+\s|\Z)",md)
    body=sm.group(1).strip() if sm else ""
    # Remove every model-authored anchor status/reporting line; canonical runtime state is the only authority.
    body=re.sub(r"(?im)^\s*(?:[-*]\s*)?(?:Anchor Outlier Pattern|Original Anchor|Anchor skeleton|Derived Safe Anchor Skeleton|Unsupported/unsafe claim element|Original claim|Medical Gate reason|Safe replacement framing|Anchor variations|Titles following anchor|Anchor-fidelity risk|Anchor-pattern minimum)\s*:\s*.*$","",body)
    body=re.sub(r"(?im)^.*no Anchor Outlier Pattern was supplied.*$","",body)
    anchor_present=bool(anchor)
    status_line,risk_line,minimum_line=_anchor_status_lines(anchor_present,count)
    if anchor:
        prefix=(status_line+"\n"+f"Original Anchor: {anchor}\n"+f"Derived Safe Anchor Skeleton: {derive_anchor_skeleton(anchor)}\n"+f"Original claim: {_anchor_original_claim(anchor)}\n"+f"Medical Gate reason: {_anchor_gate_reason(project,anchor)}\n"+f"Safe replacement framing: {_safe_anchor_replacement(rows,anchor)}\n"+f"Anchor variations: {count}\n"+f"Titles following anchor: {count}\n"+risk_line+"\n"+minimum_line)
    else:
        prefix=status_line+"\n"+risk_line+"\n"+minimum_line
    md=_replace_unique_md_section(md,"Title Strategy Summary",prefix+("\n"+body.strip() if body.strip() else ""))
    # Title Risk Report must consume the same canonical runtime anchor state. Preserve
    # model-authored risk notes, but replace/insert the anchor-fidelity status line.
    risk_match=re.search(r"(?ims)^##+\s*Title Risk Report\s*$\s*(.*?)(?=^##+\s|\Z)",md)
    if risk_match:
        risk_body=risk_match.group(1).strip()
        risk_body=re.sub(r"(?im)^\s*(?:[-*]\s*)?Anchor-fidelity risk\s*:\s*.*$","",risk_body)
        risk_body=re.sub(r"(?im)^.*anchor-fidelity risk is not applicable because no anchor pattern was supplied\.?\s*$","",risk_body)
        risk_body=re.sub(r"(?im)^.*no anchor pattern was supplied\.?\s*$","",risk_body)
        canonical_risk=risk_line+("\n"+risk_body.strip() if risk_body.strip() else "")
        md=_replace_md_section(md,"Title Risk Report",canonical_risk)
    # Remove contradictory model-authored anchor status lines outside the summary too.
    cleaned=[]
    for line in md.splitlines():
        low=line.lower()
        if "no anchor outlier pattern was supplied" in low:
            continue
        if re.match(r"^\s*(?:[-*]\s*)?anchor-fidelity risk\s*:",line,flags=re.I) and line.strip() != risk_line:
            continue
        if re.match(r"^\s*(?:[-*]\s*)?anchor-pattern minimum\s*:",line,flags=re.I) and line.strip() != minimum_line:
            continue
        cleaned.append(line)
    md="\n".join(cleaned)+("\n" if md.endswith("\n") else "")
    table=["| Rank | Title | Overall Score |","|---:|---|---:|"]+[f"| {r['rank']} | {r['title']} | {r['overall_score']} |" for r in rows]
    md=_replace_md_section(md,"15 Ranked Titles","\n".join(table))
    md=_replace_md_section(md,"Score Breakdown for Every Title",_serialize_title_score_breakdown(rows))
    md=_replace_md_section(md,"Anchor Variation Deterministic Audit",_serialize_anchor_variation_audit(anchor_results) if anchor else "No Anchor Outlier Pattern supplied; all anchor_variation values are NO.")
    promise_lines=["| Rank | Title | Hook | Bond | Project-derived reason |","|---:|---|---|---|---|"]
    for r in rows:
        pr=promise_by_id[id(r)]; reason=str(pr["content_promise_reason"]).replace("|","/")
        promise_lines.append(f"| {r['rank']} | {r['title']} | {pr['promise_hook']} | {pr['content_promise_bond']} | {reason} |")
    promise_lines.append(f"\nSource reads: {promise_inventory['source_reads']} (one batch derivation; reused for all 15 titles).")
    md=_replace_md_section(md,"Content-Promise Bond Deterministic Audit","\n".join(promise_lines))
    md=_replace_md_section(md,"Top 5 Finalists","\n".join(f"- {r['title']}" for r in finalists))
    md=_serialize_title_selection_sections(md, rows)
    # Model-authored validation status is never serialized as authority. Remove every
    # prior PASS/FAIL/PENDING line and emit one canonical pending result; the caller
    # replaces this with the deterministic validator result after artifact validation.
    md=re.sub(r"(?ims)^##+\s*Deterministic Validation\s*$.*?(?=^##+\s|\Z)", "", md)
    md=re.sub(r"(?im)^\s*Validation Result\s*:\s*(?:PASS|FAIL|PENDING DETERMINISTIC VALIDATION)\s*$", "", md)
    md=md.rstrip()+"\n\n## Deterministic Validation\n\nValidation Result: PENDING DETERMINISTIC VALIDATION\n"
    md_path.write_text(md,encoding="utf-8")

    # Post-serialization single-source assertions: MD, CSV, and summary must agree.
    md_flags=_md_anchor_breakdown(md)
    expected_flags={int(r["rank"]):r["anchor_variation"] for r in rows}
    if md_flags != expected_flags:
        return ["post-serialization MD/CSV anchor_variation mismatch"]
    sm2=re.search(r"(?ims)^##+\s*Title Strategy Summary\s*$\s*(.*?)(?=^##+\s|\Z)",md)
    summary2=sm2.group(1) if sm2 else ""
    counts=[int(x) for x in re.findall(r"(?im)^\s*(?:Anchor variations|Titles following anchor)\s*:\s*(\d+)\s*$",summary2)]
    if anchor and (counts != [count,count]):
        return [f"post-serialization summary anchor count mismatch; expected {count}, found {counts}"]
    return []

def write_title_v2_validation_result(project: Path, issues: list[str]) -> None:
    """Write the Markdown validation result from deterministic issues only."""
    path=project/"03_titles.md"
    if not path.is_file():
        return
    md=path.read_text(encoding="utf-8-sig", errors="replace")
    # Remove every model/canonicalizer-authored result block/line before writing authority.
    md=re.sub(r"(?ims)^##+\s*Deterministic Validation\s*$.*?(?=^##+\s|\Z)", "", md)
    md=re.sub(r"(?im)^\s*Validation Result\s*:\s*(?:PASS|FAIL|PENDING DETERMINISTIC VALIDATION)\s*$", "", md)
    status="FAIL" if issues else "PASS"
    detail=("\n".join(f"- {x}" for x in issues) if issues else "- No deterministic validation issues.")
    md=md.rstrip()+f"\n\n## Deterministic Validation\n\nValidation Result: {status}\n\n{detail}\n"
    path.write_text(md, encoding="utf-8")

def validate_title_v2_artifacts(project: Path, anchor_outlier_pattern: str | None = None) -> list[str]:
    """Deterministically validate Title V2 machine fields and MD/CSV selections."""
    issues: list[str] = []
    md_path, csv_path = project / "03_titles.md", project / "03_titles.csv"
    if not md_path.exists(): issues.append("03_titles.md missing")
    if not csv_path.exists(): issues.append("03_titles.csv missing")
    if issues: return issues
    # Output encoding contract: Markdown is UTF-8 (no BOM required); CSV is UTF-8 with BOM.
    md_bytes = md_path.read_bytes()
    csv_bytes = csv_path.read_bytes()
    try:
        md = md_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        issues.append(f"03_titles.md is not valid UTF-8: {exc}")
        return issues
    if not csv_bytes.startswith(b"\xef\xbb\xbf"):
        issues.append("03_titles.csv must be UTF-8 with BOM")
    try:
        csv_text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        issues.append(f"03_titles.csv is not valid UTF-8: {exc}")
        return issues
    corruption_patterns = ("\ufffd", "Ã", "Â", "â€™", "â€œ", "â€\x9d", "â€“", "â€”")
    for label, text in (("Markdown", md), ("CSV", csv_text)):
        found = next((token for token in corruption_patterns if token in text), None)
        if found is not None:
            issues.append(f"{label} contains corrupted Unicode/mojibake text: {found!r}")
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader=csv.DictReader(handle); rows=list(reader); header=reader.fieldnames or []
    if header != TITLE_V2_EXACT_HEADER:
        issues.append("03_titles.csv header does not match exact V2 schema")
        return issues
    if len(rows) != 15: issues.append(f"03_titles.csv must contain exactly 15 titles; found {len(rows)}")
    ranks=[]; titles=set(); finalists=[]
    winner=safe=experiment=None
    for i,row in enumerate(rows,1):
        rank=_strict_int(row['rank'],1,15)
        if rank is None: issues.append(f"row {i}: rank must be integer 1-15")
        else: ranks.append(rank)
        title=row['title'].strip()
        if not title: issues.append(f"row {i}: title is blank")
        if title in titles: issues.append(f"row {i}: duplicate title")
        titles.add(title)
        raw=_strict_int(row['viewer_curiosity_raw'],0,10)
        if raw is None: issues.append(f"row {i}: viewer_curiosity_raw must be integer 0-10")
        weighted=_strict_int(row['viewer_curiosity_weighted'],0,15)
        if weighted is None: issues.append(f"row {i}: viewer_curiosity_weighted must be integer 0-15")
        elif raw is not None:
            expected=int((Decimal(raw)*Decimal('1.5')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            if weighted != expected: issues.append(f"row {i}: viewer_curiosity_weighted must equal half-up {expected}")
        if _strict_int(row['overall_score'],0,100) is None: issues.append(f"row {i}: overall_score must be integer 0-100")
        if row['anchor_variation'] not in {'YES','NO'}: issues.append(f"row {i}: invalid anchor_variation {row['anchor_variation']!r}")
        if row['recommendation_type'] not in TITLE_V2_RECOMMENDATION_TYPES: issues.append(f"row {i}: invalid recommendation_type {row['recommendation_type']!r}")
        if row['thumbnail_emotion'] not in TITLE_V2_THUMBNAIL_EMOTIONS: issues.append(f"row {i}: invalid thumbnail_emotion {row['thumbnail_emotion']!r}")
        pub=row['publish_recommendation']
        if pub not in TITLE_V2_PUBLISH_RECOMMENDATIONS: issues.append(f"row {i}: invalid publish_recommendation {pub!r}")
        expected_pub=title_publish_recommendation(row)
        if pub in TITLE_V2_PUBLISH_RECOMMENDATIONS and pub != expected_pub:
            issues.append(f"row {i}: {pub} conflicts with deterministic publish_recommendation; expected {expected_pub}")
        expected_score=_title_score(row)
        score=_strict_int(row['overall_score'],0,100)
        if expected_score is not None and score is not None and score != expected_score:
            issues.append(f"row {i}: overall_score must equal deterministic component sum {expected_score}")
        if row['finalist']=='YES': finalists.append(title)
        rt=row['recommendation_type']
        if rt=='WINNER': winner=title if winner is None else '__MULTIPLE__'
        elif rt=='SAFE_ALTERNATIVE': safe=title if safe is None else '__MULTIPLE__'
        elif rt=='HIGH_UPSIDE_EXPERIMENT': experiment=title if experiment is None else '__MULTIPLE__'
    if sorted(ranks) != list(range(1,16)): issues.append("CSV ranks must be exactly 1 through 15")
    # Generation and validation share the same score-first deterministic ranking helper.
    indexed=list(enumerate(rows))
    expected_order=[row for _,row in sorted(indexed,key=lambda pair:_title_ranking_key(pair[1],pair[0]))]
    if rows != expected_order:
        for pos,(actual,expected) in enumerate(zip(rows,expected_order),1):
            if actual is not expected:
                a_score=_strict_int(actual.get("overall_score",""),0,100); e_score=_strict_int(expected.get("overall_score",""),0,100)
                if a_score is not None and e_score is not None and a_score < e_score:
                    issues.append(f"ranking must be overall_score descending: rank {pos} score {a_score} is above score {e_score}")
                else:
                    fields=[("medical_safety",15),("viewer_benefit",15),("consensus_fit",15),("audience_fit",10),("packaging_confidence",100),("risk_level",None),("viewer_curiosity_weighted",15),("search_intent_score",10),("thumbnail_compatibility",10)]
                    differing=next((f for f,_ in fields if actual.get(f)!=expected.get(f)),"stable original candidate order")
                    issues.append(f"equal-score tie-break violation: {differing} at rank {pos}; expected {expected.get('title')!r} before {actual.get('title')!r}")
                break
    if len(finalists) != 5: issues.append(f"CSV finalist flags must identify exactly 5 titles; found {len(finalists)}")
    for label,value in [('winner',winner),('safest alternative',safe),('highest-upside experiment',experiment)]:
        if value is None or value=='__MULTIPLE__': issues.append(f"CSV must identify exactly one {label}")
    md_winner=_md_selection(md,'Recommended Winner'); md_safe=_md_selection(md,'Safest High-CTR Alternative'); md_exp=_md_selection(md,'Highest-Upside Experiment')
    final_winner=_md_final_selection(md,'Recommended winner')
    final_safe=_md_final_selection(md,'Safest high-CTR alternative')
    final_exp=_md_final_selection(md,'Highest-upside experiment')
    selection_checks=(
        ('WINNER', winner, final_winner, md_winner),
        ('SAFE_ALTERNATIVE', safe, final_safe, md_safe),
        ('HIGH_UPSIDE_EXPERIMENT', experiment, final_exp, md_exp),
    )
    for recommendation_type,csv_value,final_value,dedicated_value in selection_checks:
        if csv_value in (None,'__MULTIPLE__'):
            continue
        if final_value is None or dedicated_value is None:
            issues.append(f"{recommendation_type} Markdown serialization missing")
        elif not (csv_value == final_value == dedicated_value):
            issues.append(f"{recommendation_type} serialization mismatch")
    ranked=re.search(r"(?ims)^##+\s*15 Ranked Titles\s*$\s*(.*?)(?=^##+\s|\Z)",md)
    if ranked:
        lines=[ln.strip() for ln in ranked.group(1).splitlines() if ln.strip().startswith('|')]
        if len(lines) >= 3:
            headers=[x.strip().lower() for x in lines[0].strip('|').split('|')]
            try: ri=headers.index('rank'); ti=headers.index('title'); oi=headers.index('overall score')
            except ValueError: issues.append("Markdown ranked table missing Rank/Title/Overall Score columns")
            else:
                md_rows=[]
                for ln in lines[2:]:
                    cells=[x.strip().strip('*') for x in ln.strip('|').split('|')]
                    if len(cells)>max(ri,ti,oi) and cells[ri].isdigit(): md_rows.append((int(cells[ri]),cells[ti],cells[oi]))
                if len(md_rows)!=15: issues.append(f"Markdown ranked table must contain 15 titles; found {len(md_rows)}")
                csv_trip=[(int(r['rank']),r['title'].strip(),r['overall_score'].strip()) for r in rows if r['rank'].isdigit()]
                if md_rows != csv_trip: issues.append("MD/CSV rank, title, or overall_score mismatch")
        else: issues.append("Markdown 15 Ranked Titles table missing")
    else: issues.append("Markdown 15 Ranked Titles section missing")

    md_anchor_flags=_md_anchor_breakdown(md)
    csv_anchor_flags={int(r['rank']):r['anchor_variation'] for r in rows if r['rank'].isdigit()}
    if md_anchor_flags != csv_anchor_flags:
        issues.append("MD Score Breakdown anchor_variation values must equal CSV for every rank")

    top=re.search(r"(?ims)^##+\s*Top 5 Finalists\s*$\s*(.*?)(?=^##+\s|\Z)",md)
    if top:
        for title in finalists:
            if title not in top.group(1): issues.append(f"MD/CSV finalist mismatch: {title!r} not in Markdown Top 5")
    else: issues.append("Markdown Top 5 Finalists section missing")
    anchor=(anchor_outlier_pattern or '').strip()
    summary_match = re.search(r"(?ims)^##+\s*Title Strategy Summary\s*$\s*(.*?)(?=^##+\s|\Z)", md)
    summary = summary_match.group(1) if summary_match else ""
    expected_status="PROVIDED" if anchor else "UNAVAILABLE"
    status_patterns=(
        ("strategy summary", r"(?im)^\s*Anchor Outlier Pattern\s*:\s*(PROVIDED|UNAVAILABLE)\b"),
        ("anchor-fidelity risk", r"(?im)^\s*Anchor-fidelity risk\s*:\s*(PROVIDED|UNAVAILABLE)\b"),
        ("anchor-pattern minimum", r"(?im)^\s*Anchor-pattern minimum\s*:\s*(PROVIDED|UNAVAILABLE)\b"),
    )
    observed=[]
    require_three=bool(anchor)
    for label,pat in status_patterns:
        m=re.search(pat,summary)
        if not m:
            if require_three:
                issues.append(f"{label} anchor-status report missing")
        else:
            observed.append((label,m.group(1).upper()))
    if any(status != expected_status for _,status in observed):
        issues.append("anchor status reports disagree with canonical runtime anchor presence")
    if len({status for _,status in observed}) > 1:
        issues.append("Strategy Summary, anchor-fidelity risk, and anchor-pattern minimum anchor statuses disagree")
    if anchor:
        if re.search(r"(?i)anchor(?: pattern)?[^\n]*(?:unavailable|no anchor|not provided)", summary or md):
            issues.append("supplied anchor was rewritten as unavailable in Markdown")
        if anchor not in summary:
            issues.append("runtime anchor text is absent from Title Strategy Summary audit/context")
        skeleton = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:Anchor skeleton|Derived Safe Anchor Skeleton)\s*:\s*(.+?)\s*$", summary)
        if not skeleton or skeleton.group(1).strip().lower() in {"", "unavailable", "none", "not provided"}:
            issues.append("supplied anchor requires a non-empty anchor skeleton in Title Strategy Summary")
        validation_anchor_results=classify_anchor_variations(rows, anchor, project)
        classifier_issues=sorted({str(r.get("issue") or "") for r in validation_anchor_results if r.get("issue")})
        issues.extend(x for x in classifier_issues if x not in issues)
        count=sum(bool(result["matched"]) for result in validation_anchor_results)
        for result in validation_anchor_results:
            row=result["row"]
            expected_yes=bool(result["matched"])
            actual_yes=row.get('anchor_variation')=='YES'
            if expected_yes != actual_yes:
                issues.append(f"rank {row.get('rank')}: anchor_variation disagrees with deterministic skeleton classifier")
        summary_counts={k.lower():int(v) for k,v in re.findall(r"(?im)^\s*(Anchor variations|Titles following anchor)\s*:\s*(\d+)\s*$",summary)}
        if summary_counts.get('anchor variations') != count or summary_counts.get('titles following anchor') != count:
            issues.append(f"Title Strategy Summary anchor counts must both equal CSV YES count {count}")
        if not classifier_issues and count < 8:
            issues.append(f"supplied anchor requires at least 8 deterministic anchor variations; found {count}")
        if not classifier_issues and count == 0:
            issues.append("supplied anchor cannot have all CSV anchor_variation values NO")
    try:
        if not all((project/name).is_file() for name in ("01_topic_validation.md","02_research_sheet.md","13_fact_check_log.md")):
            return issues
        promise_results,_inventory=classify_content_promises(rows,project)
        for result in promise_results:
            row=result["row"]
            if result["promise_hook"] not in TITLE_PROMISE_HOOKS: issues.append(f"rank {row.get('rank')}: invalid deterministic promise_hook")
            if result["content_promise_bond"] not in TITLE_PROMISE_BONDS: issues.append(f"rank {row.get('rank')}: invalid deterministic Content-Promise bond")
            if result["content_promise_bond"]=="FAIL" and row.get("recommendation_type") in {"WINNER","SAFE_ALTERNATIVE","HIGH_UPSIDE_EXPERIMENT"}: issues.append(f"rank {row.get('rank')}: {row.get('recommendation_type')} has Content-Promise Bond FAIL")
        block=re.search(r"(?ims)^##+\s*Content-Promise Bond Deterministic Audit\s*$\s*(.*?)(?=^##+\s|\Z)",md)
        if not block: issues.append("Markdown Content-Promise Bond audit missing")
        else:
            md_rows=[ln for ln in block.group(1).splitlines() if re.match(r"^\|\s*\d+\s*\|",ln)]
            if len(md_rows)!=15: issues.append(f"Markdown Content-Promise Bond audit must contain 15 titles; found {len(md_rows)}")
            by_rank={str(r["row"].get("rank")):r for r in promise_results}
            for row in rows:
                pr=by_rank.get(row["rank"],{}); hook=str(pr.get("promise_hook","")); bond=str(pr.get("content_promise_bond",""))
                pat=rf"^\|\s*{re.escape(row['rank'])}\s*\|.*\|\s*{re.escape(hook)}\s*\|\s*{re.escape(bond)}\s*\|"
                if not any(re.search(pat,ln) for ln in md_rows): issues.append(f"rank {row['rank']}: Markdown Content-Promise audit disagrees with deterministic result")
    except ValueError as exc:
        issues.append(str(exc))
    return issues

def validate_production_mix(avatar: int, ai_images: int, stock: int, overlays: int) -> tuple[bool, str]:
    values = {"Avatar": avatar, "AI Images": ai_images, "Stock": stock, "Overlays": overlays}
    invalid = [name for name, value in values.items() if not isinstance(value, (int, float)) or value < 0 or value > 100]
    if invalid:
        return False, "Each production mix percentage must be between 0 and 100."
    total = sum(values.values())
    if total != 100:
        return False, f"Production mix totals {total}%. It must equal exactly 100%."
    return True, "Production mix is valid."

def production_outputs(project: Path) -> dict[str, bool]:
    return {filename: (project / filename).is_file() and (project / filename).stat().st_size > 0 for filename in PRODUCTION_OUTPUT_FILES}

@dataclass
class GateResult:
    name: str; status: str; reason: str; file: str; exists: bool
    @property
    def passed(self) -> bool: return self.status in PASS_VALUES | CONDITIONAL_VALUES

@dataclass
class ProductionLock:
    locked: bool; reasons: list[str]; checks: list[GateResult]

@dataclass
class RunResult:
    returncode: int; output: str; log_path: str; started_at: str; finished_at: str; command_preview: str

@dataclass
class ScriptValidation:
    valid: bool; exists: bool; word_count: int; runtime_minutes: float; target_words_min: int; target_words_max: int
    target_runtime_min: float; target_runtime_max: float; missing_headings: list[str]; issues: list[str]; preview: str

@dataclass
class UploadResult:
    success: bool; message: str; destination: str; backup_path: str | None; validation: ScriptValidation

@dataclass
class RevisionItem:
    section: str; current_text: str; replace_with: str; reason: str; severity: str

@dataclass
class RevisionResult:
    success: bool; message: str; applied: int; skipped: int; backup_path: str | None

@dataclass
class ScriptMetrics:
    average_sentence_length: float; average_paragraph_length: float; repeated_sentence_openings: list[str]
    contractions_percent: float; read_aloud_score: float; estimated_elevenlabs_pauses: int
    rhetorical_question_count: int; estimated_narration_wpm: int; section_runtime: dict[str, float]
    reading_difficulty: float
    repeated_opening_details: list[dict[str, Any]]
    contraction_opportunities: list[dict[str, Any]]
    contraction_opportunity_count: int
    read_aloud_breakdown: dict[str, int]
    total_runtime_minutes: float
    estimated_video_duration_minutes: float
    long_sections: list[str]
    target_ranges: dict[str, str]

@dataclass
class CleanerResult:
    success: bool; changed: bool; backup_path: str | None; report_path: str; issues: list[str]


def read_text(path: Path) -> str:
    try: return path.read_text(encoding="utf-8")
    except UnicodeDecodeError: return path.read_text(encoding="utf-8-sig")
    except OSError: return ""

def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value, encoding="utf-8", newline="\n")

def load_json(path: Path, default: Any = None) -> Any:
    try: return json.loads(read_text(path)) if path.exists() else ({} if default is None else default)
    except json.JSONDecodeError: return {} if default is None else default

def save_json(path: Path, value: Any) -> None: write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")

def sync_project_prompt_state(
    state: Any,
    *,
    prompt_key: str,
    context_key: str,
    context_value: str,
    default_prompt: str,
    force_reset: bool = False,
) -> str:
    """Synchronize an editable prompt with its project/stage context.

    Defaults are installed only when the context changes or reset is explicit,
    preserving legitimate manual edits during ordinary UI reruns.
    """
    if force_reset or state.get(context_key) != context_value:
        state[prompt_key] = default_prompt
        state[context_key] = context_value
    elif prompt_key not in state:
        state[prompt_key] = default_prompt
    return str(state[prompt_key])



def sync_project_validation_context(
    state: dict[str, Any],
    *,
    context_key: str,
    selected_project: Path,
    invalidate_keys: tuple[str, ...] = (),
) -> Path:
    """Use the current dropdown selection as the only validation context.

    The returned path is freshly resolved on every render. Session state stores
    only the last context identifier so project-specific UI artifacts can be
    invalidated when the selection changes; validators never read a project
    path from session state.
    """
    current = selected_project.resolve()
    current_id = str(current)
    if state.get(context_key) != current_id:
        for key in invalidate_keys:
            state.pop(key, None)
        state[context_key] = current_id
    return current

def count_words(text: str) -> int: return len(re.findall(r"\b[\w’'-]+\b", text, flags=re.UNICODE))
def estimate_runtime_minutes(text_or_words: str | int, words_per_minute: int = 145) -> float:
    words = count_words(text_or_words) if isinstance(text_or_words, str) else max(0, int(text_or_words)); return round(words / max(1, words_per_minute), 1)
def _target_runtime(config: dict[str, Any]) -> tuple[float, float]:
    value = config.get("target_runtime_range_minutes")
    if isinstance(value, list) and len(value) >= 2: return float(value[0]), float(value[1])
    target = float(config.get("target_runtime_minutes", 25)); return max(1.0, target - 2), target + 3
def _headings(text: str) -> list[str]: return [m.group(1).strip().lower() for m in re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", text)]

def validate_final_script(project: Path, config: dict[str, Any]) -> ScriptValidation:
    path = project / "06_final_script.md"; exists = path.is_file() and path.stat().st_size > 0; text = read_text(path) if exists else ""
    words = count_words(text); wpm = int(config.get("narration_words_per_minute", 145)); runtime = estimate_runtime_minutes(words, wpm)
    runtime_min, runtime_max = _target_runtime(config); required = [str(x).strip().lower() for x in config.get("writer_required_headings", DEFAULT_REQUIRED_HEADINGS) if str(x).strip()]
    found = _headings(text)
    numbered_sections = {int(m.group(1)) for heading in found for m in [re.search(r"\bsection\s+(\d+)\b", heading, re.I)] if m}
    numbered_schema_valid = all(number in numbered_sections for number in range(1, 12))
    missing = [] if numbered_schema_valid else [h for h in required if not any(h in f for f in found)]
    issues: list[str] = []
    if not exists: issues.append("06_final_script.md is missing or empty.")
    if exists and words < int(config.get("writer_minimum_words", 300)): issues.append(f"Script is too short ({words} words).")
    if exists and not found: issues.append("Script has no Markdown headings.")
    if missing: issues.append("Missing required headings: " + ", ".join(missing) + ".")
    if exists and re.search(r"(?im)^#{1,6}\s*(runtime metrics|retention report|medical review|humanization report|config values used)", text): issues.append("QA/report content must be stored in separate 06_* report files, not 06_final_script.md.")
    if exists and not re.search(r"(?i)\b(subscribe|comment|like|share|talk to your doctor|healthcare professional|medical advice)\b", text): issues.append("No CTA or medical-safety language was detected.")
    return ScriptValidation(exists and not issues, exists, words, runtime, round(runtime_min*wpm), round(runtime_max*wpm), runtime_min, runtime_max, missing, issues, text[:12000])

def _safe_project_file(project: Path, filename: str) -> Path:
    root = project.resolve(); dest = (root / Path(filename).name).resolve()
    if dest.parent != root: raise ValueError("Unsafe destination path.")
    return dest

def _backup(project: Path, filename: str) -> Path | None:
    src = project / filename
    if not src.exists(): return None
    folder = project / "Backups"; folder.mkdir(exist_ok=True); stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = folder / f"{Path(filename).stem}_{stamp}{Path(filename).suffix}"; shutil.copy2(src, target); return target

def record_manual_event(project: Path, event: str, details: dict[str, Any] | None = None, log_dir: Path | None = None) -> Path:
    now = datetime.now().isoformat(timespec="seconds"); payload = {"event": event, "project": project.name, "timestamp": now, "details": details or {}}
    event_path = project / ".manual_events.jsonl"; event_path.parent.mkdir(parents=True, exist_ok=True)
    with event_path.open("a", encoding="utf-8", newline="\n") as h: h.write(json.dumps(payload, ensure_ascii=False)+"\n")
    save_json(project / ".last_run.json", {"returncode":0,"output":event,"log_path":str(event_path),"started_at":now,"finished_at":now,"command_preview":"manual_event","event_type":event,"details":details or {}})
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir/"manual_events.jsonl").open("a",encoding="utf-8",newline="\n") as h: h.write(json.dumps(payload,ensure_ascii=False)+"\n")
    return event_path

def save_uploaded_script(project: Path, uploaded_name: str, content: bytes, config: dict[str, Any], *, create_backup: bool=True, log_dir: Path|None=None) -> UploadResult:
    suffix=Path(uploaded_name).suffix.lower(); empty=validate_final_script(project,config)
    if suffix not in ALLOWED_SCRIPT_EXTENSIONS: return UploadResult(False,"Only .md and .txt files are allowed.","",None,empty)
    if Path(uploaded_name).name != uploaded_name or any(x in uploaded_name for x in ("/","\\","..")): return UploadResult(False,"Unsafe filename rejected.","",None,empty)
    try: text=content.decode("utf-8-sig")
    except UnicodeDecodeError: return UploadResult(False,"Upload must be UTF-8 text.","",None,empty)
    if not text.strip(): return UploadResult(False,"Uploaded script is empty.","",None,empty)
    dest=_safe_project_file(project,"06_final_script.md"); backup=_backup(project,"06_final_script.md") if dest.exists() and create_backup else None; write_text(dest,text)
    validation=validate_final_script(project,config); msg="06_final_script.md uploaded and validated successfully." if validation.valid else "Script saved, but validation failed: "+" ".join(validation.issues)
    record_manual_event(project,"writer_workspace_upload",{"source_filename":Path(uploaded_name).name,"destination":dest.name,"backup":str(backup.relative_to(project)) if backup else None,"valid":validation.valid,"word_count":validation.word_count,"runtime_minutes":validation.runtime_minutes},log_dir)
    return UploadResult(validation.valid,msg,str(dest),str(backup) if backup else None,validation)

def extract_gate_status(text: str) -> str:
    """Normalize an explicit gate status from Markdown report text."""
    if not text.strip():
        return "MISSING"
    candidates: list[str] = []
    label_pattern = re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:[-*>]\s*)*(?:overall\s+)?"
        r"(?:status|result|(?:final\s+)?verdict|gate(?:\s+(?:result|status))?)"
        r"\s*[:\-]\s*(.+?)\s*$",
        re.I,
    )
    for raw_line in text.splitlines():
        line = re.sub(r"[`*_~]", "", raw_line).strip()
        match = label_pattern.match(line)
        if match:
            candidates.append(re.sub(r"\s+", " ", match.group(1)).strip(" #.:-").upper())
    if not candidates:
        return "UNKNOWN"
    value = candidates[0]
    if re.search(r"\bPASS\s+WITH\s+SUGGESTIONS\b", value):
        return "PASS WITH SUGGESTIONS"
    if re.search(r"\b(?:PASS\s+WITH\s+(?:REVISIONS|REQUIRED\s+EDITS)|CONDITIONAL\s+PASS)\b", value):
        return "PASS WITH REVISIONS"
    if re.search(r"\b(?:FAIL|FAILED|BLOCKED|REJECTED)\b", value):
        return "FAIL"
    if re.search(r"\b(?:PASS|PASSED|APPROVED|READY)\b", value):
        return "PASS"
    return "UNKNOWN"

def _gate_filename(gate_name: str, config: dict[str, Any] | None = None, filename: str | None = None) -> str:
    if filename:
        return filename
    config = config or {}
    if gate_name == "Narrative QA":
        return str(config.get("narrative_qa_output", "14_narrative_qa.md"))
    if gate_name == "Medical Gate 2":
        return str(config.get("medical_gate_2_output", "15_medical_gate_2.md"))
    return QA_REPORTS.get(gate_name, STAGE_FILES.get(gate_name, gate_name))

def get_gate_status(project: Path, gate_name: str, config: dict[str, Any] | None = None, *, filename: str | None = None) -> GateResult:
    """Read the current report from disk on every call; no session/cache state is used."""
    report_name = _gate_filename(gate_name, config, filename)
    path = project / report_name
    exists = path.is_file() and path.stat().st_size > 0
    status = extract_gate_status(read_text(path)) if exists else "MISSING"
    if not exists:
        reason = f"{report_name} is missing."
    elif status == "UNKNOWN":
        reason = f"{report_name} does not contain a recognizable Status/Verdict."
    elif status == "FAIL":
        issue_match=re.search(r"(?ims)^##\s+Issues\s*$\s*[-*]\s*(.+?)(?:\n|$)",read_text(path))
        reason = issue_match.group(1).strip() if issue_match else f"{gate_name} reported FAIL."
    else:
        reason = f"{gate_name} reported {status}."
    if gate_name == "Production Cleaner" and status == "PASS" and not production_cleaner_is_current(project, config or {}):
        status="FAIL"; reason="Production Cleaner report is stale because the production source changed. Run Production Cleaner again."
    return GateResult(gate_name, status, reason, report_name, exists)

def gate_result(project: Path, name: str, filename: str) -> GateResult:
    """Backward-compatible alias routed through the shared disk-backed helper."""
    return get_gate_status(project, name, filename=filename)

def parse_revision_patch(text: str) -> list[RevisionItem]:
    blocks=re.split(r"(?im)^\s*(?:###\s*)?(?:revision\s*\d+|patch\s*\d+)\s*$",text)
    items=[]
    for block in blocks:
        fields={}
        for key in ["Section","Current Text","Replace With","Reason","Severity"]:
            m=re.search(rf"(?ims)^\s*(?:[-*]\s*)?{re.escape(key)}\s*:\s*(.*?)(?=^\s*(?:[-*]\s*)?(?:Section|Current Text|Replace With|Reason|Severity)\s*:|\Z)",block)
            if m: fields[key]=m.group(1).strip().strip('`')
        if fields.get("Current Text") and fields.get("Replace With"):
            items.append(RevisionItem(fields.get("Section","Unspecified"),fields["Current Text"],fields["Replace With"],fields.get("Reason",""),fields.get("Severity","MEDIUM").upper()))
    return items

def apply_revision_patch(project: Path, report_filename: str, *, log_dir: Path|None=None) -> RevisionResult:
    script_path=_safe_project_file(project,"06_final_script.md"); report_path=_safe_project_file(project,report_filename)
    if not script_path.exists(): return RevisionResult(False,"06_final_script.md is missing.",0,0,None)
    items=parse_revision_patch(read_text(report_path));
    if not items: return RevisionResult(False,"No structured Revision Patch was found.",0,0,None)
    text=read_text(script_path); backup=_backup(project,"06_final_script.md"); applied=0; skipped=0
    for item in items:
        if item.current_text in text: text=text.replace(item.current_text,item.replace_with,1); applied+=1
        else: skipped+=1
    if applied: write_text(script_path,text)
    record_manual_event(project,"revision_patch_applied",{"source_report":report_filename,"applied":applied,"skipped":skipped,"backup":str(backup.relative_to(project)) if backup else None},log_dir)
    return RevisionResult(applied>0,f"Applied {applied} revision(s); skipped {skipped} unmatched item(s).",applied,skipped,str(backup) if backup else None)

def script_quality_metrics(text: str, config: dict[str,Any]|None=None) -> ScriptMetrics:
    config=config or {}
    narration=re.sub(r"(?ms)^#{1,6}.*?$|\[Visual Cue.*?\]","",text)
    raw_sentences=[s.strip() for s in re.split(r"(?<=[.!?])\s+",narration) if count_words(s)>0]
    paragraphs=[p.strip() for p in re.split(r"\n\s*\n",narration) if count_words(p)>0]
    words=max(1,count_words(narration)); sentence_count=max(1,len(raw_sentences))
    avg_sentence=words/sentence_count; avg_para=words/max(1,len(paragraphs))

    section_matches=list(re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$",text))
    sentence_locations=[]; global_sentence=0
    for index,match in enumerate(section_matches):
        section=match.group(1).strip(); body=text[match.end():section_matches[index+1].start() if index+1<len(section_matches) else len(text)]
        body=re.sub(r"\[Visual Cue.*?\]","",body,flags=re.S)
        for local,sentence in enumerate([s.strip() for s in re.split(r"(?<=[.!?])\s+",body) if count_words(s)>0],1):
            global_sentence+=1
            opening=" ".join(re.findall(r"\b[\w’'-]+\b",sentence.lower())[:2])
            sentence_locations.append({"opening":opening,"section":section,"sentence":global_sentence,"section_sentence":local})
    if not sentence_locations:
        for sentence in raw_sentences:
            global_sentence+=1
            opening=" ".join(re.findall(r"\b[\w’'-]+\b",sentence.lower())[:2])
            sentence_locations.append({"opening":opening,"section":"Script","sentence":global_sentence,"section_sentence":global_sentence})
    grouped={}
    for item in sentence_locations:
        if item["opening"]: grouped.setdefault(item["opening"],[]).append(item)
    details=[]
    for opening,occurrences in sorted(grouped.items(),key=lambda item:(-len(item[1]),item[0])):
        count=len(occurrences)
        if count<3: continue
        ratio=count/max(1,len(sentence_locations))
        level="High" if count>=8 or ratio>=0.10 else ("Moderate" if count>=4 or ratio>=0.05 else "Good")
        details.append({"opening":opening,"count":count,"level":level,"occurrences":[{"section":x["section"],"sentence":x["sentence"],"section_sentence":x["section_sentence"]} for x in occurrences]})
    repeated=[f"{item['opening']} ({item['count']}x)" for item in details]

    contraction_matches=re.findall(r"\b\w+[’'](?:t|re|ve|ll|d|m|s)\b",narration,re.I)
    contractions=len(contraction_matches)
    patterns=[(r"\bit is\b","It is","It's"),(r"\bi am\b","I am","I'm"),(r"\bthat is\b","That is","That's"),(r"\bwe are\b","We are","We're"),(r"\byou are\b","You are","You're"),(r"\bdo not\b","Do not","Don't"),(r"\bcannot\b","Cannot","Can't"),(r"\bwill not\b","Will not","Won't"),(r"\bthey are\b","They are","They're")]
    opportunities=[]
    for pattern,source,replacement in patterns:
        count=len(re.findall(pattern,narration,re.I))
        if count: opportunities.append({"source":source,"replacement":replacement,"count":count})

    syllables=sum(max(1,len(re.findall(r"[aeiouy]+",w.lower()))) for w in re.findall(r"\b[a-zA-Z]+\b",narration))
    difficulty=round(206.835-1.015*(words/sentence_count)-84.6*(syllables/words),1)
    pauses=len(re.findall(r"[,;:—–]|\.\.\.",narration))+len(paragraphs)
    rhetorical=len(re.findall(r"\?",narration)); wpm=int(config.get("narration_words_per_minute",145))
    sections={}
    for i,m in enumerate(section_matches): sections[m.group(1).strip()]=estimate_runtime_minutes(text[m.end():section_matches[i+1].start() if i+1<len(section_matches) else len(text)],wpm)
    total_runtime=estimate_runtime_minutes(words,wpm)
    estimated_video=round(total_runtime+float(config.get("estimated_video_overhead_minutes",0)),1)
    average_section=(sum(sections.values())/len(sections)) if sections else 0
    long_sections=[name for name,value in sections.items() if average_section and value>average_section*1.35 and value-average_section>=0.5]

    sentence_variety=max(0,min(100,round(100-abs(avg_sentence-16)*4)))
    contraction_pct=contractions/words*100
    contractions_score=max(0,min(100,round(100-abs(contraction_pct-3.0)*14)))
    paragraph_flow=max(0,min(100,round(100-abs(avg_para-55)*1.4)))
    repeated_penalty=sum(12 if item["level"]=="High" else 6 if item["level"]=="Moderate" else 2 for item in details)
    repeated_score=max(0,100-repeated_penalty)
    pauses_per_100=pauses/words*100
    breathing_score=max(0,min(100,round(100-abs(pauses_per_100-6)*8)))
    breakdown={"Sentence Variety":sentence_variety,"Contractions":contractions_score,"Paragraph Flow":paragraph_flow,"Repeated Openings":repeated_score,"Breathing Rhythm":breathing_score}
    score=round(sum(breakdown.values())/len(breakdown))
    targets={"Average sentence length":"12–20 words","Average paragraph length":"35–75 words","Contractions":"2–5% of words","Repeated openings":"0–3 repeated patterns; no High items","Read-aloud score":"75–100","Breathing rhythm":"4–8 pause cues per 100 words","Reading ease":"60–80 preferred"}
    return ScriptMetrics(round(avg_sentence,1),round(avg_para,1),repeated[:10],round(contraction_pct,1),float(score),pauses,rhetorical,wpm,sections,difficulty,details,opportunities,sum(x["count"] for x in opportunities),breakdown,total_runtime,estimated_video,long_sections,targets)

def _production_source_filename(config: dict[str, Any]) -> str:
    return str(config.get("voice_script_suffix", "06a_voice_script.md"))

def _file_sha256(path: Path) -> str:
    if not path.is_file(): return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _cleaner_report_source_hash(report_text: str) -> str:
    match = re.search(r"(?im)^Source SHA-256:\s*`?([0-9a-f]{64})`?\s*$", report_text)
    return match.group(1).lower() if match else ""

def production_cleaner_is_current(project: Path, config: dict[str, Any]) -> bool:
    source = project / _production_source_filename(config)
    report = project / str(config.get("production_clean_report", "production_clean_report.md"))
    if not source.is_file() or not report.is_file(): return False
    return _cleaner_report_source_hash(read_text(report)) == _file_sha256(source)

def production_cleaner_prerequisites(project: Path, config: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return the Production Cleaner entry prerequisites.

    Production is intentionally decoupled from the upstream editorial workflow.
    A non-empty canonical voice script is the only editorial prerequisite; QA,
    Medical Gate, checklist, title, outline, and other upstream artifacts are
    not Production readiness dependencies.
    """
    source_name=_production_source_filename(config)
    path=project/source_name
    if not path.is_file() or path.stat().st_size == 0:
        return False,[f"Voice script is missing or empty: {source_name}."]
    if not read_text(path).strip():
        return False,[f"Voice script is missing or empty: {source_name}."]
    return True,[]

def clean_production_script(project: Path, config: dict[str,Any], *, log_dir: Path|None=None) -> CleanerResult:
    source_name=_production_source_filename(config); path=project/source_name
    report=project/str(config.get("production_clean_report", "production_clean_report.md"))
    if not path.is_file() or path.stat().st_size == 0:
        issues=[f"{source_name} is missing or empty."]
        write_text(report,f"# Production Cleaner Report\n\nStatus: FAIL\n\nSource File: {source_name}\n\n## Issues\n- {issues[0]}\n")
        return CleanerResult(False,False,None,str(report),issues)
    original=read_text(path)
    # The production voice script is intentionally plain narration. Only safe
    # whitespace cleanup is permitted; structural/editorial content is never
    # removed or rewritten automatically.
    text=re.sub(r"(?m)[ \t]+$","",original)
    text=re.sub(r"\n{3,}","\n\n",text).strip()+"\n"
    issues=[]

    if re.search(r"(?m)^\s{0,3}#{1,6}\s+\S",text):
        issues.append("Markdown heading(s) found; the production voice script must contain plain narration with no headings.")
    markdown_patterns = [
        (r"```|~~~", "Markdown code fence(s) found."),
        (r"(?m)^\s*[-*+]\s+\S", "Markdown bullet list(s) found."),
        (r"(?m)^\s*\d+[.)]\s+\S", "Markdown numbered list(s) found."),
        (r"\*\*[^*]+\*\*|__[^_]+__", "Markdown bold formatting found."),
        (r"(?<!\*)\*[^*\n]+\*(?!\*)|(?<!_)_[^_\n]+_(?!_)", "Markdown emphasis formatting found."),
        (r"\[[^\]\n]+\]\([^\)\n]+\)", "Markdown link(s) found."),
        (r"(?m)^\s*>\s+\S", "Markdown blockquote(s) found."),
    ]
    for pattern,message in markdown_patterns:
        if re.search(pattern,text): issues.append(message)

    if re.search(r"(?i)\[\s*(?:visual\s+cue|b-?roll|on[- ]screen|graphic|image|scene)[^\]]*\]",text):
        issues.append("Visual Cue or production direction block(s) found; voice narration must not contain them.")
    if re.search(r"(?i)(?:^|\n)\s*(?:editor(?:'s)?\s+note|qa\s+note|reviewer\s+note|production\s+note)\s*[:\-]",text):
        issues.append("Editor, QA, reviewer, or production note(s) found.")
    if re.search(r"<\/?(?:speak|break|prosody|phoneme|say-as|sub|voice|amazon:[^ >]+)(?:\s[^>]*)?>",text,re.I):
        issues.append("SSML tag(s) found; the production voice script must be plain narration.")
    if re.search(r"\[[^\]\n]+\]",text):
        issues.append("Bracket tag(s) found; the production voice script must not contain bracketed directions or notes.")

    final_text=read_text(project/"06_final_script.md")
    cta_pattern=r"\b(?:subscribe|like\s+(?:this|the)\s+video|leave\s+(?:a\s+)?comment|comment\s+below|share\s+(?:this|the)\s+video)\b"
    if re.search(cta_pattern,final_text,re.I) and not re.search(cta_pattern,text,re.I):
        issues.append("CTA present in 06_final_script.md is missing from the production voice script.")
    host_tokens=[]
    configured_host=str(config.get("host_name","")).strip()
    if configured_host: host_tokens.append(re.escape(configured_host))
    host_tokens.extend([r"Health Educator",r"Adrian Westbrook"])
    host_pattern=r"(?:"+"|".join(host_tokens)+r")"
    if re.search(host_pattern,final_text,re.I) and not re.search(host_pattern,text,re.I):
        issues.append("Host identity present in 06_final_script.md is missing from the production voice script.")

    # Medical meaning/narration wording preservation is guaranteed by allowing
    # whitespace-only edits. Compare lexical content as a safety invariant.
    lexical=lambda value: re.sub(r"\s+"," ",value).strip()
    if lexical(text) != lexical(original):
        issues.append("Cleaner safety check failed: a non-whitespace narration change was detected.")

    changed=text!=original; backup=_backup(project,source_name) if changed else None
    if changed: write_text(path,text)
    source_hash=_file_sha256(path); status="PASS" if not issues else "FAIL"
    write_text(report,f"# Production Cleaner Report\n\nStatus: {status}\n\nSource File: {source_name}\nSource SHA-256: `{source_hash}`\nGenerated At: {datetime.now().isoformat(timespec='seconds')}\n\n## Validation\n- Plain narration checked\n- No Markdown/headings checked\n- No Visual Cue blocks checked\n- No editor or QA notes checked\n- No SSML checked\n- No bracket tags checked\n- CTA preservation checked\n- Host identity preservation checked\n- Narration wording preserved (whitespace-only cleanup)\n- Medical meaning preserved by prohibiting wording changes\n\n## Changes\n- Whitespace formatting changed: {'Yes' if changed else 'No'}\n\n## Issues\n"+("\n".join(f"- {i}" for i in issues) if issues else "- None")+"\n")
    record_manual_event(project,"production_cleaner_run",{"status":status,"source":source_name,"source_sha256":source_hash,"changed":changed,"issues":len(issues),"backup":str(backup.relative_to(project)) if backup else None},log_dir)
    return CleanerResult(not issues,changed,str(backup) if backup else None,str(report),issues)

def ensure_production_cleaner(project: Path, config: dict[str, Any], *, log_dir: Path|None=None, force: bool=False) -> CleanerResult | None:
    ready,_=production_cleaner_prerequisites(project,config)
    if not ready: return None
    if not force and production_cleaner_is_current(project,config): return None
    return clean_production_script(project,config,log_dir=log_dir)

def _content_check(project:Path,name:str,pattern:str,filename:str="06_final_script.md",fail_reason:str|None=None) -> GateResult:
    text=read_text(project/filename); ok=bool(re.search(pattern,text,re.I|re.M))
    reason=f"{name} passed." if ok else (fail_reason or f"{name} was not detected in {filename}.")
    return GateResult(name,"PASS" if ok else "FAIL",reason,filename,(project/filename).exists())

def production_lock(project: Path, config: dict[str,Any]) -> ProductionLock:
    """Production entry gate: only a usable canonical voice script is required.

    Upstream editorial workflow status and Production Cleaner status are not
    entry blockers.  The Production page/downstream runtime may still run the
    cleaner and all normal Production validations, but readiness itself is
    intentionally based only on 06a_voice_script.md (or configured source).
    """
    source_name=_production_source_filename(config)
    source=project/source_name
    voice_ready=source.is_file() and source.stat().st_size>0 and bool(read_text(source).strip())
    voice=GateResult(
        "Voice Script",
        "PASS" if voice_ready else "FAIL",
        f"{source_name} is ready." if voice_ready else f"{source_name} is missing or empty.",
        source_name,
        voice_ready,
    )
    reasons=[] if voice_ready else [voice.reason]
    override=load_json(project/".production_override.json",{})
    active=bool(override.get("enabled")) and bool(config.get("allow_production_override",False))
    return ProductionLock(bool(reasons) and not active,reasons,[voice])

def narrative_qa_ready(project:Path,config:dict[str,Any])->tuple[bool,list[str]]:
    reasons=[]
    if not (project/"05_script_outline.md").is_file(): reasons.append("05_script_outline.md is missing.")
    v=validate_final_script(project,config)
    if not v.valid: reasons.extend(v.issues)
    return not reasons,reasons

TITLE_STAGE_REQUIRED_FILES = ("01_topic_validation.md", "02_research_sheet.md", "13_fact_check_log.md")

def title_stage_dependencies(project: Path) -> tuple[bool, list[str]]:
    """Require only the approved Title-stage project-file dependencies."""
    reasons = [f"{name} is missing." for name in TITLE_STAGE_REQUIRED_FILES if not (project / name).is_file()]
    return not reasons, reasons

def stage_ready(project:Path,stage:str,config:dict[str,Any])->tuple[bool,list[str]]:
    if stage=="Thumbnail":
        anchor=resolve_title_anchor(project)
        reasons=[]
        if not anchor: reasons.append("Authoritative project Anchor / Outlier Title is missing from project.json.")
        for name in ("01_topic_validation.md","02_research_sheet.md","13_fact_check_log.md"):
            if not (project/name).is_file(): reasons.append(f"{name} is missing.")
        return not reasons,reasons
    if stage=="Narrative QA": return narrative_qa_ready(project,config)
    if stage=="Medical Gate 2":
        g=get_gate_status(project,"Narrative QA",config); ready=g.status=="PASS"; return ready,([] if ready else [g.reason])
    if stage=="Speech Optimizer":
        source=project/"06_final_script.md"
        ready=source.is_file() and source.stat().st_size>0 and bool(read_text(source).strip())
        return ready,([] if ready else ["06_final_script.md is missing or empty."])
    if stage=="Production Package":
        lock=production_lock(project,config)
        blockers=[c.reason for c in lock.checks if c.name != "Production Cleaner" and not c.passed]
        return not blockers,blockers
    return True,[]

def qa_dashboard(project:Path,config:dict[str,Any])->list[dict[str,Any]]:
    rows=[]
    for name,default in QA_REPORTS.items():
        fn=str(config.get({"Narrative QA":"narrative_qa_output","Medical Gate 2":"medical_gate_2_output"}.get(name,""),default)) if name in {"Narrative QA","Medical Gate 2"} else default
        path=project/fn; g=get_gate_status(project,name,config,filename=fn); text=read_text(path); issues=len(re.findall(r"(?im)^\s*(?:[-*]|\d+[.)])\s+",text))
        last_run=datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds") if path.exists() else "-"
        rows.append({"Stage":name,"Status":g.status,"Issues":issues,"Last Run":last_run,"Report":fn})
    return rows

def file_progress(project:Path)->tuple[int,int,int]:
    total=len(PIPELINE); present=sum(1 for _,f in PIPELINE if (project/f).exists()); return present,total,round(present/total*100) if total else 0

def weighted_progress(project:Path,config:dict[str,Any])->int:
    weights={"01_topic_validation.md":6,"02_research_sheet.md":9,"04_thumbnail_concepts.md":5,"05_script_outline.md":8,"opus_writer_package.md":6,"06_final_script.md":14,"14_narrative_qa.md":9,"15_medical_gate_2.md":10,"06a_voice_script.md":6,"production_clean_report.md":5,"07_production_sheet.csv":7,"08_youtube_metadata.md":4,"16_project_summary.md":5}
    score=0
    for fn,w in weights.items():
        if not (project/fn).exists(): continue
        if fn=="06_final_script.md" and not validate_final_script(project,config).valid: continue
        if fn in {"14_narrative_qa.md","15_medical_gate_2.md","production_clean_report.md"} and not get_gate_status(project,fn,filename=fn).passed: continue
        score+=w
    return min(100,score)

def next_action(project:Path,config:dict[str,Any])->str:
    for label,fn in PIPELINE:
        if label=="Writer Workspace" and not validate_final_script(project,config).valid:return label
        if label in {"Narrative QA","Medical Gate 2","Speech Optimizer","Production Package"}:
            ready,_=stage_ready(project,label,config)
            if not ready:return label
        if label in {"Narrative QA","Medical Gate 2"} and not get_gate_status(project,label,config,filename=fn).passed:return label
        if not (project/fn).exists():return label
    return "Resolve Production Lock" if production_lock(project,config).locked else "Complete"

def detect_codex_template(config:dict[str,Any])->str:
    configured=str(config.get("codex_cli_command","")).strip()
    if configured:return configured
    executable=shutil.which("codex.cmd") or shutil.which("codex"); return f'"{executable}" exec --sandbox workspace-write --skip-git-repo-check {{prompt}}' if executable else ""
def _format_command(template:str,prompt:str,project:Path)->str:
    if "{prompt}" not in template:raise ValueError("Codex command template must include {prompt}.")
    qp=shlex.quote(prompt) if os.name!="nt" else subprocess.list2cmdline([prompt]); qproj=shlex.quote(str(project)) if os.name!="nt" else subprocess.list2cmdline([str(project)]); return template.replace("{prompt}",qp).replace("{project}",qproj)
def run_codex(template:str,prompt:str,project:Path,root:Path,log_dir:Path,timeout_seconds:int=3600)->RunResult:
    log_dir.mkdir(parents=True,exist_ok=True); start=datetime.now(); cmd=_format_command(template,prompt,project); log=log_dir/f"{project.name}_{start.strftime('%Y%m%d_%H%M%S')}.log"
    try:
        c=subprocess.run(cmd,cwd=root,shell=True,capture_output=True,text=True,timeout=timeout_seconds,env=os.environ.copy()); output=(c.stdout or "")+(("\n"+c.stderr) if c.stderr else ""); code=c.returncode
    except subprocess.TimeoutExpired: output="Command timed out."; code=124
    except Exception as exc: output=f"Direct run failed: {exc}"; code=1
    finish=datetime.now(); write_text(log,output); result=RunResult(code,output[-20000:],str(log),start.isoformat(timespec="seconds"),finish.isoformat(timespec="seconds"),cmd[:500]); save_json(project/".last_run.json",asdict(result)); return result

def validate_project(project:Path,config:dict[str,Any])->list[str]:
    issues=[]
    for required in ["project.json","production_settings.json"]:
        if not (project/required).exists():issues.append(f"Missing {required}")
    if (project/"06_final_script.md").exists():issues.extend(validate_final_script(project,config).issues)
    for fn in ["14_narrative_qa.md","15_medical_gate_2.md","production_clean_report.md"]:
        if (project/fn).exists() and extract_gate_status(read_text(project/fn))=="UNKNOWN":issues.append(f"{fn}: add an explicit Status: PASS / PASS WITH REVISIONS / FAIL")
    return issues
