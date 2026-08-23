from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path

from timeline_builder import REQUIRED_COLUMNS, parse_timeline_time

CHAPTER_HEADER = "## 5. Chapters / Timestamps"
_SCENE_RE = re.compile(r"\b(S\d+)\b", re.IGNORECASE)
_TIME_PREFIX_RE = re.compile(r"^\s*(?:\d{1,2}:)?\d{1,3}:\d{2}(?:\.\d+)?\s+[-–—|:]?\s*")


class SEOChapterError(ValueError):
    pass


@dataclass(frozen=True)
class Chapter:
    scene_id: str
    label: str
    seconds: int


def _load_timeline(path: Path) -> dict[str, float]:
    if not path.is_file():
        raise SEOChapterError("Actual Timeline required for SEO chapter timestamps.")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        missing = [c for c in REQUIRED_COLUMNS if c not in fields]
        if missing:
            raise SEOChapterError("08_actual_timeline.csv schema mismatch; missing: " + ", ".join(missing))
        rows = list(reader)
    if not rows:
        raise SEOChapterError("Actual Timeline required for SEO chapter timestamps.")
    out: dict[str, float] = {}
    for index, row in enumerate(rows, start=2):
        scene = (row.get("Scene ID") or "").strip().upper()
        if not scene:
            raise SEOChapterError(f"08_actual_timeline.csv row {index} has no Scene ID.")
        if scene in out:
            raise SEOChapterError(f"08_actual_timeline.csv contains duplicate Scene ID: {scene}")
        try:
            out[scene] = parse_timeline_time(row.get("Actual Audio Start"))
        except ValueError as exc:
            raise SEOChapterError(f"08_actual_timeline.csv row {index} has invalid Actual Audio Start: {exc}") from exc
    return out


def format_youtube_time(seconds: int) -> str:
    if seconds < 0:
        raise SEOChapterError("Chapter timestamp cannot be negative.")
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _extract_section(text: str) -> tuple[str, str, str]:
    match = re.search(r"(?mi)^##\s*5\.\s*Chapters\s*/\s*Timestamps\s*$", text)
    if not match:
        raise SEOChapterError(f"SEO output is missing required section: {CHAPTER_HEADER}")
    next_header = re.search(r"(?m)^##\s+", text[match.end():])
    end = match.end() + next_header.start() if next_header else len(text)
    return text[:match.start()], text[match.end():end], text[end:]


def _parse_candidates(body: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^[-*+]\s+", "", line)
        scene_match = _SCENE_RE.search(line)
        if not scene_match:
            continue
        scene = scene_match.group(1).upper()
        # Any LLM-provided timestamp is discarded before label extraction.
        line = _TIME_PREFIX_RE.sub("", line)
        line = line.replace(f"[{scene}]", "").replace(f"[{scene.lower()}]", "")
        line = re.sub(rf"\b{re.escape(scene)}\b", "", line, flags=re.IGNORECASE)
        label = re.sub(r"^[\s:|\-–—]+|[\s:|\-–—]+$", "", line).strip()
        if label:
            candidates.append((scene, label))
    if not candidates:
        raise SEOChapterError("SEO chapters contain no resolvable scene anchors; timestamps were not guessed.")
    return candidates


def finalize_chapters(metadata_text: str, timeline_path: Path) -> tuple[str, list[str]]:
    timeline = _load_timeline(timeline_path)
    before, body, after = _extract_section(metadata_text)
    candidates = _parse_candidates(body)
    diagnostics: list[str] = []
    resolved: list[Chapter] = []
    seen_seconds: set[int] = set()
    last_second = -1

    for position, (scene, label) in enumerate(candidates):
        if scene not in timeline:
            diagnostics.append(f"Dropped chapter '{label}': scene {scene} not found in Actual Timeline.")
            continue
        # Floor fractional actual starts: never display a chapter later than its mapped boundary.
        displayed = math.floor(timeline[scene])
        if not resolved:
            displayed = 0  # YouTube first-chapter rule; only allowed timing special case.
        elif displayed <= last_second or displayed in seen_seconds:
            diagnostics.append(f"Dropped chapter '{label}': displayed timestamp would be duplicate/non-monotonic.")
            continue
        resolved.append(Chapter(scene, label, displayed))
        seen_seconds.add(displayed)
        last_second = displayed

    if not resolved:
        raise SEOChapterError("No valid SEO chapters remain after Actual Timeline mapping.")
    lines = [f"{format_youtube_time(ch.seconds)} {ch.label}" for ch in resolved]
    final_body = "\n\n" + "\n".join(lines) + "\n\n"
    return before + CHAPTER_HEADER + final_body + after.lstrip("\n"), diagnostics


def finalize_project_seo(project: Path) -> list[str]:
    metadata = project / "08_youtube_metadata.md"
    timeline = project / "08_actual_timeline.csv"
    if not metadata.is_file():
        raise SEOChapterError("SEO Agent did not create 08_youtube_metadata.md.")
    original = metadata.read_text(encoding="utf-8-sig")
    finalized, diagnostics = finalize_chapters(original, timeline)
    metadata.write_text(finalized, encoding="utf-8")
    return diagnostics
