from __future__ import annotations

import csv
import io
import json
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from evidence_overlay import EvidenceCandidate, analyze_project_evidence

from timeline_builder import parse_timeline_time

ALLOWED_TYPES = {"KEY FACT", "NUMBER", "CONTRAST", "TAKEAWAY", "SAFETY", "ACTION", "MYTH CHECK"}
ARTIFACT_NAME = "11_text_overlays.csv"
REQUIRED_FIELDS = ["Overlay Number", "Script Line Start", "Script Line End", "Overlay Text", "Overlay Type"]
MOJIBAKE = {"â‰ˆ": "≈", "Â·": "·", "â€“": "–", "â€”": "—"}
DEFAULT_TEXT_OVERLAY_STYLE = {
    # Centralized V1 profile for the dedicated CapCut Text Overlay track.
    "font_family": "Arial",
    "font_size": 18.0,
    "bold": True,
    "italic": False,
    "alignment": 1,
    "text_color": "#FFFFFF",
    "stroke_color": "#000000",
    "stroke_width": 0.10,
    "shadow": True,
    # CapCut normalized transform: x=0 centers horizontally; negative y places
    # the overlay in the lower-center safe/caption-style region.
    "transform_x": 0.0,
    "transform_y": -0.28,
    "max_lines": 2,
    # Whole-text accents only. Mixed spans are intentionally not invented.
    "type_colors": {
        "NUMBER": "#FEEF08",
        "CONTRAST": "#FEEF08",
        "ACTION": "#FEEF08",
        "SAFETY": "#FE0000",
    },
}

@dataclass
class OverlayRecord:
    overlay_id: str
    overlay_number: int
    start_seconds: float | None
    end_seconds: float | None
    duration_seconds: float | None
    overlay_text: str
    overlay_type: str
    script_line_start: str
    script_line_end: str
    timing_source: str
    status: str
    priority: int
    warnings: list[str] = field(default_factory=list)
    overlay_class: str = "STANDARD"
    heading: str = ""
    bullet_1: str = ""
    bullet_2: str = ""
    bullet_3: str = ""
    source_trace: str = ""
    claim_key: str = ""
    allowed_start_seconds: float | None = None
    allowed_end_seconds: float | None = None
    diagnostic: str = ""

@dataclass
class ValidationResult:
    records: list[OverlayRecord]
    errors: list[str]
    warnings: list[str]
    narration_source: Path
    timeline_ready: bool

    @property
    def passed(self) -> bool:
        return not self.errors and bool(self.records) and all(r.status in {"READY", "WARNING"} for r in self.records)


def clean_text(value: Any) -> str:
    text = str(value or "")
    for bad, good in MOJIBAKE.items():
        text = text.replace(bad, good)
    # Conservative generic repair for common UTF-8 decoded as latin-1/cp1252.
    if any(marker in text for marker in ("Ã", "Â", "â")):
        try:
            repaired = text.encode("cp1252").decode("utf-8")
            if repaired.count("�") <= text.count("�"):
                text = repaired
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return unicodedata.normalize("NFC", text)


def normalize_anchor(value: str) -> str:
    text = clean_text(value)
    text = text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    text = text.replace("—", "-").replace("–", "-")
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value: str) -> list[str]:
    return normalize_anchor(value).split()


def parse_opus_csv(data: bytes | str) -> list[dict[str, str]]:
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else str(data)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("CSV header is missing.")
    missing = [name for name in REQUIRED_FIELDS if name not in reader.fieldnames]
    if missing:
        raise ValueError("Missing required CSV columns: " + ", ".join(missing))
    rows = []
    for raw in reader:
        if not any(str(v or "").strip() for v in raw.values()):
            continue
        rows.append({name: clean_text(raw.get(name, "")).strip() for name in REQUIRED_FIELDS})
    return rows


def load_actual_timeline(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            start = parse_timeline_time(row.get("Actual Audio Start", ""))
            end = parse_timeline_time(row.get("Actual Audio End", ""))
            rows.append({**row, "_start": start, "_end": end, "_tokens": _tokens(row.get("Script Text", ""))})
    return rows


def _find_sequence(haystack: list[str], needle: list[str]) -> tuple[int, int] | None:
    if not needle or len(needle) > len(haystack):
        return None
    exact = [i for i in range(len(haystack)-len(needle)+1) if haystack[i:i+len(needle)] == needle]
    if len(exact) == 1:
        return exact[0], exact[0] + len(needle) - 1
    if len(exact) > 1:
        return None
    # Only allow very high similarity for harmless tokenization differences.
    best = None
    for i in range(len(haystack)-len(needle)+1):
        score = SequenceMatcher(None, needle, haystack[i:i+len(needle)], autojunk=False).ratio()
        if best is None or score > best[0]:
            best = (score, i)
    if best and best[0] >= 0.96:
        return best[1], best[1] + len(needle) - 1
    return None


def _timeline_token_map(rows: list[dict[str, Any]]) -> tuple[list[str], list[tuple[int,int]]]:
    tokens, owners = [], []
    for row_index, row in enumerate(rows):
        for token_index, token in enumerate(row["_tokens"]):
            tokens.append(token); owners.append((row_index, token_index))
    return tokens, owners


def _load_word_stream(project: Path) -> list[dict[str, Any]]:
    transcript_dir = project / "avatar_transcripts"
    if not transcript_dir.is_dir():
        return []
    def key(path: Path):
        m = re.search(r"(\d+)$", path.stem)
        return (int(m.group(1)) if m else 10**9, path.name)
    out, offset = [], 0.0
    for path in sorted(transcript_dir.glob("*.json"), key=key):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        words = payload.get("words") or []
        duration = float(payload.get("duration") or 0.0)
        if not duration:
            segments = payload.get("segments") or []
            duration = max((float(s.get("end", 0.0) or 0.0) for s in segments if isinstance(s, dict)), default=0.0)
        if words:
            for item in words:
                if not isinstance(item, dict): continue
                word = str(item.get("word") or item.get("text") or "").strip()
                toks = _tokens(word)
                if not toks: continue
                start = offset + float(item.get("start", 0.0) or 0.0)
                end = offset + float(item.get("end", item.get("start", 0.0)) or 0.0)
                for tok in toks:
                    out.append({"token": tok, "start": start, "end": end, "chunk": path.name})
        offset += duration
    return out


def _align_timeline_to_words(timeline_tokens: list[str], words: list[dict[str, Any]]) -> dict[int, int]:
    transcript_tokens = [w["token"] for w in words]
    matcher = SequenceMatcher(None, timeline_tokens, transcript_tokens, autojunk=False)
    mapping = {}
    for block in matcher.get_matching_blocks():
        for d in range(block.size): mapping[block.a+d] = block.b+d
    return mapping


def _resolve_anchor_in_word_stream(
    words: list[dict[str, Any]],
    anchor_tokens: list[str],
    window_start: float,
    window_end: float,
) -> tuple[int, int, str] | None:
    """Resolve an anchor directly against transcript words inside its timeline window.

    This is deliberately local: duplicate phrases elsewhere in the narration cannot
    steal the match. Exact normalized tokens win; a conservative fuzzy match is
    allowed only for harmless ASR/tokenization differences.
    """
    if not words or not anchor_tokens:
        return None
    candidates = [i for i, w in enumerate(words)
                  if float(w.get("end", 0.0)) >= window_start - 2.0
                  and float(w.get("start", 0.0)) <= window_end + max(2.0, min(12.0, len(anchor_tokens) * 0.6))]
    if not candidates:
        return None
    lo, hi = min(candidates), max(candidates)
    stream = [w["token"] for w in words]
    n = len(anchor_tokens)
    exact = []
    for i in range(lo, hi - n + 2):
        if stream[i:i+n] == anchor_tokens:
            exact.append(i)
    if exact:
        # If repeated inside the same narrow window, prefer the occurrence nearest
        # the window start; this is deterministic and stays within the matched scene.
        i = min(exact, key=lambda x: abs(float(words[x]["start"]) - window_start))
        return i, i+n-1, "word_timestamps_local_exact"

    # ASR can drop/add punctuation (already normalized) or misrecognize one token.
    # Search small length deltas and require a strong similarity score.
    best = None
    for length in range(max(1, n-1), n+2):
        for i in range(lo, hi - length + 2):
            seq = stream[i:i+length]
            score = SequenceMatcher(None, anchor_tokens, seq, autojunk=False).ratio()
            if best is None or score > best[0]:
                best = (score, i, i+length-1)
    if best and best[0] >= 0.88:
        return best[1], best[2], "word_timestamps_local_fuzzy"
    return None


def _priority(overlay_type: str) -> int:
    return 200 if overlay_type == "SAFETY" else 100


def validate_rows(project: Path, rows: list[dict[str, str]]) -> ValidationResult:
    project = Path(project).resolve()
    timeline_path = project / "08_actual_timeline.csv"
    timeline = load_actual_timeline(timeline_path)
    errors, warnings, records = [], [], []
    if not timeline:
        return ValidationResult([], ["08_actual_timeline.csv is missing or empty."], [], timeline_path, False)
    timeline_tokens, owners = _timeline_token_map(timeline)
    words = _load_word_stream(project)
    mapping = _align_timeline_to_words(timeline_tokens, words) if words else {}

    intervals = []
    seen_numbers = set()
    for idx, row in enumerate(rows, 1):
        try: number = int(str(row["Overlay Number"]).strip())
        except ValueError:
            errors.append(f"Row {idx}: Overlay Number must be an integer."); continue
        if number in seen_numbers:
            errors.append(f"Row {idx}: duplicate Overlay Number {number}."); continue
        seen_numbers.add(number)
        typ = row["Overlay Type"].strip().upper()
        if typ not in ALLOWED_TYPES:
            errors.append(f"Overlay {number}: unknown Overlay Type '{row['Overlay Type']}'."); continue
        start_anchor, end_anchor = row["Script Line Start"], row["Script Line End"]
        start_seq = _find_sequence(timeline_tokens, _tokens(start_anchor))
        end_seq = _find_sequence(timeline_tokens, _tokens(end_anchor))
        if not start_seq or not end_seq or end_seq[1] < start_seq[0]:
            errors.append(f"Overlay {number}: script anchor mismatch.")
            records.append(OverlayRecord(f"OVL{number:03d}", number, None, None, None, row["Overlay Text"], typ, start_anchor, end_anchor, "unresolved", "MISMATCH", _priority(typ)))
            continue
        start_token, end_token = start_seq[0], end_seq[1]
        timing_source = "word_timestamps"
        rec_warnings = []
        start_row = owners[start_token][0]; end_row = owners[end_token][0]
        allowed_start = timeline[start_row]["_start"]
        allowed_end = timeline[end_row]["_end"]
        if start_token in mapping and end_token in mapping:
            start = words[mapping[start_token]]["start"]
            end = words[mapping[end_token]]["end"]
        else:
            # Global SequenceMatcher can leave endpoint tokens unmapped even when
            # the exact spoken phrase exists. Re-resolve each anchor locally inside
            # the already-proven Actual Timeline rows before falling back to rows.
            start_local = _resolve_anchor_in_word_stream(
                words, _tokens(start_anchor), timeline[start_row]["_start"], timeline[start_row]["_end"]
            )
            end_local = _resolve_anchor_in_word_stream(
                words, _tokens(end_anchor), timeline[end_row]["_start"], timeline[end_row]["_end"]
            )
            if start_local and end_local and end_local[1] >= start_local[0]:
                start = words[start_local[0]]["start"]
                end = words[end_local[1]]["end"]
                timing_source = (
                    "word_timestamps_local_fuzzy"
                    if "fuzzy" in (start_local[2], end_local[2])
                    else "word_timestamps_local_exact"
                )
                if timing_source.endswith("fuzzy"):
                    rec_warnings.append("Word-level anchor timing resolved with a local normalized/fuzzy transcript match.")
            else:
                start = timeline[start_row]["_start"]; end = timeline[end_row]["_end"]
                timing_source = "actual_timeline_boundary_fallback"
                rec_warnings.append("Word-level anchor could not be resolved after local normalized/fuzzy matching; used narrowest existing Actual Timeline row boundaries.")
        if end <= start:
            errors.append(f"Overlay {number}: resolved duration is not positive."); continue
        text = row["Overlay Text"]
        duration = end-start
        if duration < 1.5 and len(_tokens(text)) > 4 or duration < 2.5 and len(_tokens(text)) > 8:
            rec_warnings.append("Overlay may be too short for comfortable reading; timing was not extended.")
        status = "WARNING" if rec_warnings else "READY"
        rec = OverlayRecord(f"OVL{number:03d}", number, round(start,6), round(end,6), round(duration,6), text, typ, start_anchor, end_anchor, timing_source, status, _priority(typ), rec_warnings, allowed_start_seconds=round(allowed_start,6), allowed_end_seconds=round(allowed_end,6))
        records.append(rec); intervals.append(rec)
        warnings.extend(f"Overlay {number}: {w}" for w in rec_warnings)

    ordered = sorted([r for r in intervals if r.start_seconds is not None], key=lambda r: (r.start_seconds, r.end_seconds))
    for a,b in zip(ordered, ordered[1:]):
        if b.start_seconds < a.end_seconds:
            msg = f"Normal text overlays overlap: {a.overlay_id} and {b.overlay_id}."
            errors.append(msg); a.status = b.status = "CONFLICT"
    return ValidationResult(records, errors, warnings, timeline_path, True)


def visual_text(text: str) -> str:
    return re.sub(r"\s*\|\s*", "\n", clean_text(text).strip())


def backup_existing(path: Path) -> Path | None:
    if not path.exists(): return None
    from datetime import datetime
    backup_dir = path.parent / "backups"; backup_dir.mkdir(exist_ok=True)
    dest = backup_dir / f"{path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{path.suffix}"
    shutil.copy2(path, dest); return dest


DEFAULT_BREATHING_GAP_SECONDS = 0.25


def _evidence_record(candidate: EvidenceCandidate, number: int) -> OverlayRecord:
    b = candidate.bullets
    return OverlayRecord(
        overlay_id=f"EVD{number:03d}", overlay_number=number,
        start_seconds=round(candidate.start_seconds, 6), end_seconds=round(candidate.end_seconds, 6),
        duration_seconds=round(candidate.end_seconds-candidate.start_seconds, 6), overlay_text="",
        overlay_type="KEY FACT", script_line_start=candidate.script_line_start,
        script_line_end=candidate.script_line_end, timing_source="actual_timeline_evidence_anchor",
        status="READY", priority=candidate.priority, overlay_class="EVIDENCE",
        heading=candidate.heading, bullet_1=b[0], bullet_2=b[1], bullet_3=b[2],
        source_trace=candidate.source_trace, claim_key=candidate.claim_key,
        allowed_start_seconds=candidate.start_seconds, allowed_end_seconds=candidate.end_seconds,
    )


def _intersects(a: OverlayRecord, b: OverlayRecord, gap: float = 0.0) -> bool:
    return bool(a.start_seconds is not None and a.end_seconds is not None and b.start_seconds is not None and b.end_seconds is not None
                and b.start_seconds < a.end_seconds + gap and a.start_seconds < b.end_seconds + gap)


def _evidence_rank(r: OverlayRecord) -> tuple[int, int, int, str]:
    try:
        trace = json.loads(r.source_trace or "{}")
        source_strength = 1 if trace.get("source_matches") else 0
        medical_strength = 1 if trace.get("medical_matches") else 0
    except json.JSONDecodeError:
        source_strength = medical_strength = 0
    specificity = len(re.findall(r"\d", " ".join([r.heading, r.bullet_1, r.bullet_2, r.bullet_3])))
    return (source_strength, medical_strength, specificity, f"{-r.overlay_number:08d}")


def schedule_unified_overlays(standard_records: list[OverlayRecord], evidence_records: list[OverlayRecord], breathing_gap: float = DEFAULT_BREATHING_GAP_SECONDS, project_name: str | None = None) -> tuple[list[OverlayRecord], list[str], list[str]]:
    """Deterministic Phase-2 scheduler. Evidence never moves; Standard may shift only inside its narration window."""
    warnings: list[str] = []
    errors: list[str] = []
    # Canonical Evidence validation before scheduling.
    valid_evidence: list[OverlayRecord] = []
    seen_claims: set[str] = set()
    for ev in evidence_records:
        if ev.overlay_class != "EVIDENCE" or not ev.heading.strip() or any(not x.strip() for x in (ev.bullet_1, ev.bullet_2, ev.bullet_3)):
            ev.status="DROPPED"; ev.diagnostic="EVIDENCE_DROPPED_MALFORMED_CONTENT"; warnings.append(f"{ev.overlay_id}: {ev.diagnostic}"); continue
        if not ev.claim_key.strip():
            ev.status="DROPPED"; ev.diagnostic="EVIDENCE_DROPPED_MISSING_CLAIM_KEY"; warnings.append(f"{ev.overlay_id}: {ev.diagnostic}"); continue
        try: trace=json.loads(ev.source_trace or "{}")
        except json.JSONDecodeError:
            trace={}
        if not trace.get("source_matches"):
            ev.status="DROPPED"; ev.diagnostic="EVIDENCE_DROPPED_INVALID_SOURCE_TRACE"; warnings.append(f"{ev.overlay_id}: {ev.diagnostic}"); continue
        if project_name is not None and trace.get("project") != project_name:
            errors.append(f"{ev.overlay_id}: CROSS_PROJECT_EVIDENCE_SOURCE")
            continue
        if ev.claim_key in seen_claims:
            ev.status="DROPPED"; ev.diagnostic="EVIDENCE_DROPPED_DUPLICATE_CLAIM"; warnings.append(f"{ev.overlay_id}: {ev.diagnostic}"); continue
        seen_claims.add(ev.claim_key); valid_evidence.append(ev)
    # Evidence-vs-Evidence: stable rank, then earlier narration/order.
    kept_evidence: list[OverlayRecord] = []
    for ev in sorted(valid_evidence, key=lambda r: (r.start_seconds or 0, r.overlay_number, r.overlay_id)):
        conflicts = [x for x in kept_evidence if _intersects(x, ev, breathing_gap)]
        if not conflicts:
            kept_evidence.append(ev); continue
        pool = conflicts + [ev]
        winner = sorted(pool, key=lambda r: (_evidence_rank(r), -(r.start_seconds or 0), -r.overlay_number), reverse=True)[0]
        for loser in pool:
            if loser is winner: continue
            loser.status = "DROPPED"; loser.diagnostic = "EVIDENCE_DROPPED_FOR_EVIDENCE_COLLISION"
            warnings.append(f"{loser.overlay_id}: {loser.diagnostic}")
            if loser in kept_evidence: kept_evidence.remove(loser)
        if winner not in kept_evidence: kept_evidence.append(winner)

    occupied = sorted(kept_evidence, key=lambda r: (r.start_seconds or 0, r.overlay_id))
    kept_standard: list[OverlayRecord] = []
    for st in sorted(standard_records, key=lambda r: (r.start_seconds or 0, r.overlay_number)):
        if st.start_seconds is None or st.end_seconds is None or st.status not in {"READY", "WARNING"}:
            kept_standard.append(st); continue
        conflicts = [ev for ev in occupied if _intersects(st, ev, breathing_gap)]
        if not conflicts:
            kept_standard.append(st); continue
        duration = float(st.duration_seconds or (st.end_seconds-st.start_seconds))
        lo = st.allowed_start_seconds if st.allowed_start_seconds is not None else st.start_seconds
        hi = st.allowed_end_seconds if st.allowed_end_seconds is not None else st.end_seconds
        candidates: list[float] = []
        for ev in conflicts:
            candidates += [ev.start_seconds - breathing_gap - duration, ev.end_seconds + breathing_gap]
        valid = []
        for ns in candidates:
            ne = ns + duration
            if ns < lo - 1e-9 or ne > hi + 1e-9 or ne <= ns: continue
            probe = OverlayRecord("probe",0,ns,ne,duration,"","KEY FACT","","","","READY",100)
            if any(_intersects(probe, x, breathing_gap) for x in occupied + kept_standard if x.status in {"READY","WARNING"}): continue
            valid.append((abs(ns-st.start_seconds), ns, ne))
        if valid:
            _, ns, ne = sorted(valid)[0]
            st.start_seconds=round(ns,6); st.end_seconds=round(ne,6); st.duration_seconds=round(duration,6)
            st.timing_source += "+evidence_collision_shift"
            st.warnings.append("STANDARD_SHIFTED_FOR_EVIDENCE_COLLISION")
            st.status="WARNING"; warnings.append(f"{st.overlay_id}: STANDARD_SHIFTED_FOR_EVIDENCE_COLLISION")
            kept_standard.append(st)
        else:
            st.status="DROPPED"; st.diagnostic="STANDARD_DROPPED_FOR_EVIDENCE_COLLISION"
            warnings.append(f"{st.overlay_id}: {st.diagnostic}")

    survivors = [r for r in kept_standard + kept_evidence if r.status in {"READY","WARNING"}]
    survivors.sort(key=lambda r: (r.start_seconds or 0, 0 if r.overlay_class=="EVIDENCE" else 1, r.overlay_number))
    for i,a in enumerate(survivors):
        for b in survivors[i+1:]:
            if b.start_seconds is not None and a.end_seconds is not None and b.start_seconds >= a.end_seconds + breathing_gap: break
            if _intersects(a,b,0.0) and (a.overlay_class=="EVIDENCE" or b.overlay_class=="EVIDENCE"):
                errors.append(f"Unresolved unified overlay collision: {a.overlay_id} and {b.overlay_id}.")
    return survivors, errors, warnings


def build_unified_records(project: Path, standard_result: ValidationResult, breathing_gap: float = DEFAULT_BREATHING_GAP_SECONDS) -> tuple[list[OverlayRecord], list[str], list[str]]:
    timeline = load_actual_timeline(Path(project).resolve()/"08_actual_timeline.csv")
    candidates, diagnostics = analyze_project_evidence(project, timeline)
    next_number = max((r.overlay_number for r in standard_result.records), default=0) + 1
    evidence = [_evidence_record(c, next_number+i) for i,c in enumerate(candidates)]
    records, errors, warnings = schedule_unified_overlays(list(standard_result.records), evidence, breathing_gap, Path(project).resolve().name)
    warnings = diagnostics + warnings
    return records, errors, warnings


def write_artifact(project: Path, result: ValidationResult) -> Path:
    if not result.passed: raise ValueError("Overlay validation must pass before artifact generation.")
    path = Path(project).resolve() / ARTIFACT_NAME
    records, unified_errors, unified_warnings = build_unified_records(project, result)
    if unified_errors: raise ValueError("; ".join(unified_errors))
    backup_existing(path)
    fields = ["overlay_id","overlay_number","start_seconds","end_seconds","duration_seconds","overlay_class","overlay_text","overlay_type","heading","bullet_1","bullet_2","bullet_3","source_trace","claim_key","script_line_start","script_line_end","timing_source","status","priority"]
    with path.open("w", encoding="utf-8-sig", newline="") as h:
        w=csv.DictWriter(h, fieldnames=fields); w.writeheader()
        for r in records:
            w.writerow({f:getattr(r,f) for f in fields})
    return path


def load_artifact(path: Path) -> list[dict[str, Any]]:
    """Backward compatible: legacy artifacts without overlay_class are STANDARD."""
    if not path.is_file(): return []
    out=[]
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        reader=csv.DictReader(h)
        for row in reader:
            row["overlay_class"]=(row.get("overlay_class") or "STANDARD").strip().upper()
            if row["overlay_class"] not in {"STANDARD","EVIDENCE"}: raise ValueError(f"Malformed overlay_class: {row['overlay_class']}")
            row["start_seconds"]=float(row["start_seconds"]); row["end_seconds"]=float(row["end_seconds"]); row["duration_seconds"]=float(row["duration_seconds"]); row["priority"]=int(row.get("priority") or 100)
            for field_name in ("heading","bullet_1","bullet_2","bullet_3","source_trace","claim_key"):
                row.setdefault(field_name, "")
            out.append(row)
    return out
