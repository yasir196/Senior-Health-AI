from __future__ import annotations

import csv
import io
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable


REQUIRED_OPUS_COLUMNS = ("Image Number", "Script Line", "AI Image Prompt")
OPTIONAL_OPUS_COLUMNS = ("Scene Type",)
IGNORED_OPUS_COLUMNS = ("Timing",)


@dataclass(frozen=True)
class ProductionImageSlot:
    image_number: int
    scene_id: str
    production_script_line: str
    production_start: str
    production_end: str
    actual_timing: str
    narrative_purpose: str
    narrative_context: str
    production_image_prompt_id: str
    selected_asset_path: str

    @property
    def filename(self) -> str:
        selected = self.selected_asset_path.strip().replace("\\", "/")
        if selected:
            name = Path(selected).name
            if re.fullmatch(r"image_\d+\.png", name, re.IGNORECASE):
                return name
        return f"image_{self.image_number:03d}.png"


@dataclass(frozen=True)
class OpusPromptRow:
    image_number: int
    script_line: str
    ai_image_prompt: str
    scene_type: str
    source_row_number: int


@dataclass(frozen=True)
class MappingRow:
    image_number: int
    scene_id: str
    production_script_line: str
    opus_script_line: str
    scene_type: str
    match_status: str
    similarity: float
    prompt: str


@dataclass(frozen=True)
class ImportValidation:
    passed: bool
    production_count: int
    imported_count: int
    mappings: tuple[MappingRow, ...]
    errors: tuple[str, ...]


_MOJIBAKE = {
    "â€”": "—",
    "â€“": "–",
    "â€˜": "‘",
    "â€™": "’",
    "â€œ": "“",
    "â€\x9d": "”",
    "â€¦": "…",
    "Â": "",
}


def clean_text(value: object, *, collapse_whitespace: bool = False) -> str:
    text = "" if value is None else str(value)
    for bad, good in _MOJIBAKE.items():
        text = text.replace(bad, good)
    text = unicodedata.normalize("NFKC", text).replace("\ufeff", "")
    if collapse_whitespace:
        text = re.sub(r"\s+", " ", text)
    else:
        text = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    return text.strip()


def normalize_script_line(value: object) -> str:
    text = clean_text(value, collapse_whitespace=True).lower()
    text = text.translate(str.maketrans({
        "“": '"', "”": '"', "„": '"', "‟": '"',
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "—": "-", "–": "-", "−": "-", "‑": "-",
    }))
    # Punctuation differences must not affect validation. Apostrophes are removed so
    # "don't" and "dont" compare as the same narration wording.
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def script_lines_match(production: str, opus: str) -> tuple[bool, float]:
    left = normalize_script_line(production)
    right = normalize_script_line(opus)
    if not left or not right:
        return False, 0.0
    if left == right:
        return True, 1.0
    # A CSV script line may include a slightly wider excerpt than the Production cell.
    if min(len(left), len(right)) >= 24 and (left in right or right in left):
        ratio = min(len(left), len(right)) / max(len(left), len(right))
        return ratio >= 0.72, ratio
    ratio = SequenceMatcher(None, left, right, autojunk=False).ratio()
    return ratio >= 0.90, ratio


def _read_csv_rows(source: bytes | str | Path) -> tuple[list[dict[str, str]], list[str]]:
    if isinstance(source, Path):
        raw = source.read_bytes()
    elif isinstance(source, bytes):
        raw = source
    else:
        raw = str(source).encode("utf-8")
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fieldnames = [clean_text(x, collapse_whitespace=True) for x in (reader.fieldnames or [])]
    rows: list[dict[str, str]] = []
    for source_row in reader:
        normalized: dict[str, str] = {}
        for key, value in source_row.items():
            if key is None:
                continue
            normalized[clean_text(key, collapse_whitespace=True)] = "" if value is None else str(value)
        rows.append(normalized)
    return rows, fieldnames


def _actual_timing_by_scene(project: Path) -> dict[str, tuple[str, str]]:
    path = Path(project) / "08_actual_timeline.csv"
    if not path.is_file():
        return {}
    rows, _ = _read_csv_rows(path)
    result: dict[str, tuple[str, str]] = {}
    for row in rows:
        sid = clean_text(row.get("Scene ID") or row.get("scene_id") or "", collapse_whitespace=True)
        if not sid:
            continue
        start = clean_text(
            row.get("Actual Audio Start") or row.get("start_time") or row.get("actual_start") or "",
            collapse_whitespace=True,
        )
        end = clean_text(
            row.get("Actual Audio End") or row.get("end_time") or row.get("actual_end") or "",
            collapse_whitespace=True,
        )
        if start or end:
            result[sid] = (start, end)
    return result


def load_production_ai_image_slots(project: Path) -> list[ProductionImageSlot]:
    project = Path(project).resolve()
    sheet = project / "07_production_sheet.csv"
    if not sheet.is_file():
        raise FileNotFoundError(f"Production Sheet not found: {sheet}")
    rows, _ = _read_csv_rows(sheet)
    actual = _actual_timing_by_scene(project)
    slots: list[ProductionImageSlot] = []
    for row in rows:
        asset_type = clean_text(row.get("recommended_asset_type") or row.get("asset_type") or "", collapse_whitespace=True).upper()
        if asset_type != "AI_IMAGE":
            continue
        number = len(slots) + 1
        scene_id = clean_text(row.get("scene_id", ""), collapse_whitespace=True)
        prod_start = clean_text(row.get("start_time", ""), collapse_whitespace=True)
        prod_end = clean_text(row.get("end_time", ""), collapse_whitespace=True)
        if scene_id in actual:
            start, end = actual[scene_id]
            timing = f"{start} → {end}".strip()
        else:
            timing = f"{prod_start} → {prod_end}".strip()
        slots.append(ProductionImageSlot(
            image_number=number,
            scene_id=scene_id,
            production_script_line=clean_text(row.get("script_excerpt", row.get("script_text", "")), collapse_whitespace=True),
            production_start=prod_start,
            production_end=prod_end,
            actual_timing=timing,
            narrative_purpose=clean_text(row.get("scene_purpose", ""), collapse_whitespace=True),
            narrative_context=clean_text(row.get("narrative_context", ""), collapse_whitespace=True),
            production_image_prompt_id=clean_text(row.get("image_prompt_id", ""), collapse_whitespace=True),
            selected_asset_path=clean_text(row.get("selected_asset_path", ""), collapse_whitespace=True),
        ))
    return slots


def parse_opus_csv(source: bytes | str | Path) -> tuple[list[OpusPromptRow], list[str]]:
    rows, fieldnames = _read_csv_rows(source)
    lookup = {name.casefold(): name for name in fieldnames}
    missing = [name for name in REQUIRED_OPUS_COLUMNS if name.casefold() not in lookup]
    if missing:
        return [], ["Missing required Opus CSV column(s): " + ", ".join(missing)]

    def col(name: str) -> str:
        return lookup.get(name.casefold(), name)

    errors: list[str] = []
    parsed: list[OpusPromptRow] = []
    raw_numbers: list[int] = []
    for idx, row in enumerate(rows, start=2):
        number_raw = clean_text(row.get(col("Image Number"), ""), collapse_whitespace=True)
        if not re.fullmatch(r"\d+", number_raw):
            errors.append(f"Row {idx}: Image Number must be numeric; got {number_raw!r}.")
            continue
        number = int(number_raw)
        raw_numbers.append(number)
        prompt = clean_text(row.get(col("AI Image Prompt"), ""), collapse_whitespace=True)
        if not prompt:
            errors.append(f"Row {idx}: AI Image Prompt is empty.")
        parsed.append(OpusPromptRow(
            image_number=number,
            script_line=clean_text(row.get(col("Script Line"), ""), collapse_whitespace=True),
            ai_image_prompt=prompt,
            scene_type=clean_text(row.get(col("Scene Type"), ""), collapse_whitespace=True) if "scene type" in lookup else "",
            source_row_number=idx,
        ))

    if len(raw_numbers) != len(set(raw_numbers)):
        duplicates = sorted(n for n in set(raw_numbers) if raw_numbers.count(n) > 1)
        errors.append("Duplicate Image Number value(s): " + ", ".join(map(str, duplicates)) + ".")
    if raw_numbers:
        expected_set = set(range(1, len(raw_numbers) + 1))
        missing_numbers = sorted(expected_set - set(raw_numbers))
        if missing_numbers:
            errors.append("Missing Image Number value(s): " + ", ".join(map(str, missing_numbers)) + ".")
        if raw_numbers != list(range(1, len(raw_numbers) + 1)):
            errors.append("Image Number values are out of order; rows must be sequential 1..N.")
    return parsed, errors


def validate_import(project: Path, opus_source: bytes | str | Path) -> ImportValidation:
    slots = load_production_ai_image_slots(project)
    opus_rows, errors = parse_opus_csv(opus_source)
    if len(slots) != len(opus_rows):
        errors.append(f"Count mismatch: Production AI_IMAGE slots = {len(slots)}; imported Opus prompts = {len(opus_rows)}.")

    mappings: list[MappingRow] = []
    by_number = {row.image_number: row for row in opus_rows}
    for slot in slots:
        opus = by_number.get(slot.image_number)
        if opus is None:
            mappings.append(MappingRow(slot.image_number, slot.scene_id, slot.production_script_line, "", "", "MISSING", 0.0, ""))
            continue
        matches, similarity = script_lines_match(slot.production_script_line, opus.script_line)
        status = "MATCH" if matches else "MISMATCH"
        if not matches:
            errors.append(f"IMAGE {slot.image_number:03d}: Production Script Line does not match Opus Script Line.")
        mappings.append(MappingRow(
            image_number=slot.image_number,
            scene_id=slot.scene_id,
            production_script_line=slot.production_script_line,
            opus_script_line=opus.script_line,
            scene_type=opus.scene_type,
            match_status=status,
            similarity=similarity,
            prompt=opus.ai_image_prompt,
        ))
    return ImportValidation(not errors, len(slots), len(opus_rows), tuple(mappings), tuple(dict.fromkeys(errors)))


def _existing_field_by_image(project: Path, label: str) -> dict[int, str]:
    path = Path(project) / "10_image_prompts.md"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8-sig")
    matches = list(re.finditer(r"(?m)^### IMAGE\s+(\d+)\s*$", text))
    out: dict[int, str] = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[match.end():end]
        field = re.search(rf"(?mi)^- {re.escape(label)}:\s*(.*)$", block)
        if field:
            out[int(match.group(1))] = field.group(1).strip()
    return out


def build_image_prompts_markdown(project: Path, opus_source: bytes | str | Path) -> tuple[str, ImportValidation]:
    project = Path(project).resolve()
    validation = validate_import(project, opus_source)
    if not validation.passed:
        raise ValueError("Opus prompt import validation failed: " + " | ".join(validation.errors))
    slots = load_production_ai_image_slots(project)
    rows, parse_errors = parse_opus_csv(opus_source)
    if parse_errors:
        raise ValueError("Opus prompt import validation failed: " + " | ".join(parse_errors))
    by_number = {r.image_number: r for r in rows}
    negative = _existing_field_by_image(project, "Negative Prompt")
    style = _existing_field_by_image(project, "Style Notes")

    lines = [
        "# AI Image Prompts — Imported from Opus",
        "",
        "> Source mapping: `07_production_sheet.csv` AI_IMAGE assignment order + externally supplied Opus prompts.",
        "> Opus CSV `Timing` is ignored. Timing remains authoritative from the existing project pipeline.",
        "",
    ]
    for slot in slots:
        opus = by_number[slot.image_number]
        # Keep prompt on one line because the existing Image Generation parser consumes this field line-wise.
        prompt = clean_text(opus.ai_image_prompt, collapse_whitespace=True)
        lines.extend([
            f"### IMAGE {slot.image_number:03d}",
            "",
            f"- Filename: {slot.filename}",
            f"- image_prompt_id: IMG{slot.image_number:03d}",
            f"- Scene ID: {slot.scene_id}",
            f"- Actual Timing: {slot.actual_timing}",
            f"- Narrative Purpose: {slot.narrative_purpose}",
            f'- Script Context: "{slot.production_script_line}"',
            f"- Narrative Context: {slot.narrative_context}",
            f"- Scene Type: {opus.scene_type}",
            f"- Final AI IMAGE PROMPT: {prompt}",
        ])
        if negative.get(slot.image_number):
            lines.append(f"- Negative Prompt: {negative[slot.image_number]}")
        if style.get(slot.image_number):
            lines.append(f"- Style Notes: {style[slot.image_number]}")
        lines.append("")
    lines.extend([
        "## Opus Import Validation",
        "",
        f"- Production AI_IMAGE Count: {validation.production_count}",
        f"- Imported Prompt Count: {validation.imported_count}",
        "- Image Number Validation: PASS",
        "- Script Line Validation: PASS",
        "- Opus Timing Used: NO",
        "- Mapping: Production AI_IMAGE assignment order ↔ Opus Image Number",
        "- Status: PASS",
        "",
    ])
    return "\n".join(lines), validation


def backup_existing_prompt_file(project: Path) -> Path | None:
    project = Path(project).resolve()
    source = project / "10_image_prompts.md"
    if not source.is_file():
        return None
    folder = project / "Backups"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = folder / f"10_image_prompts_{stamp}.md"
    shutil.copy2(source, target)
    return target


def write_image_prompts(project: Path, opus_source: bytes | str | Path) -> tuple[Path, Path | None, ImportValidation]:
    project = Path(project).resolve()
    markdown, validation = build_image_prompts_markdown(project, opus_source)
    backup = backup_existing_prompt_file(project)
    output = project / "10_image_prompts.md"
    output.write_text(markdown, encoding="utf-8", newline="\n")
    return output, backup, validation
