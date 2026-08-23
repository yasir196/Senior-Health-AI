from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from csv_safety import validate_script_text


REQUIRED_COLUMNS = ["Scene ID", "Script Text", "Actual Audio Start", "Actual Audio End", "Duration", "Avatar Chunk", "Timing Source"]
SCHEMA_VERSION = "1.1"
DEFAULT_DURATION_TOLERANCE_SECONDS = 0.15

class TimelineBuildError(ValueError):
    pass

@dataclass(frozen=True)
class TimelineBuildResult:
    success: bool
    manifest_path: Path
    scenes: int
    duration_seconds: float
    warnings: list[str]


def parse_timeline_time(value: Any) -> float:
    """Parse a timeline timestamp into non-negative seconds.

    Accepted forms are numeric seconds, MM:SS[.fraction], and
    HH:MM:SS[.fraction]. The function deliberately rejects ambiguous or
    malformed values rather than attempting to repair them.
    """
    if isinstance(value, bool):
        raise ValueError(f"invalid timeline time: {value!r}")
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        text = str(value).strip()
        if not text:
            raise ValueError("timeline time is empty")
        parts = text.split(":")
        try:
            if len(parts) == 1:
                result = float(parts[0])
            elif len(parts) == 2:
                minutes_text, seconds_text = parts
                if not minutes_text.isdigit() or not seconds_text:
                    raise ValueError
                minutes = int(minutes_text)
                seconds = float(seconds_text)
                if seconds < 0 or seconds >= 60:
                    raise ValueError
                result = minutes * 60.0 + seconds
            elif len(parts) == 3:
                hours_text, minutes_text, seconds_text = parts
                if not hours_text.isdigit() or not minutes_text.isdigit() or not seconds_text:
                    raise ValueError
                hours = int(hours_text)
                minutes = int(minutes_text)
                seconds = float(seconds_text)
                if minutes >= 60 or seconds < 0 or seconds >= 60:
                    raise ValueError
                result = hours * 3600.0 + minutes * 60.0 + seconds
            else:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid timeline time: {value!r}") from exc
    if result < 0:
        raise ValueError(f"negative timeline time is not allowed: {value!r}")
    if result == float("inf") or result != result:
        raise ValueError(f"invalid timeline time: {value!r}")
    return result


def _timeline_time(value: Any, column: str, row: int) -> float:
    try:
        return parse_timeline_time(value)
    except (TypeError, ValueError) as exc:
        raise TimelineBuildError(f"Row {row}: invalid {column}: {value!r} ({exc})") from exc


def _numeric_seconds(value: Any, column: str, row: int) -> float:
    try:
        text = str(value).strip()
        if not text or ":" in text:
            raise ValueError
        result = float(text)
    except (TypeError, ValueError) as exc:
        raise TimelineBuildError(f"Row {row}: invalid {column}: {value!r}; expected numeric seconds") from exc
    if result < 0:
        raise TimelineBuildError(f"Row {row}: negative {column} is not allowed")
    if result == float("inf") or result != result:
        raise TimelineBuildError(f"Row {row}: invalid {column}: {value!r}")
    return result


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()




def _normalize_avatar_reference(value: str) -> str:
    name = str(value).strip().replace("\\", "/")
    if not name:
        raise TimelineBuildError("Avatar reference is missing")
    path = Path(name)
    if path.is_absolute():
        return str(path)
    if name.lower().startswith("avatars/"):
        return name
    if not Path(name).suffix:
        name = f"{name}.mp4"
    return f"avatars/{name}"


def _split_avatar_references(value: str) -> list[str]:
    raw = str(value).strip()
    parts = [part.strip() for part in raw.replace(" TO ", " to ").replace(" To ", " to ").split(" to ")]
    references = [_normalize_avatar_reference(part) for part in parts if part]
    if not references:
        raise TimelineBuildError("Avatar reference is missing")
    return references

def _discover_production_asset(project: Path, *, kind: str, prompt_id: str, slot_index: int, selected: str) -> str:
    """Resolve a real production asset using the canonical prompt ID or legacy slot name.

    Production sheets use IMG001/BR001 IDs, while older downstream code expected
    image_001/broll_001. Prefer an explicit selected_asset_path, then discover the
    actual file already present under assets/images or assets/broll. Return a
    project-relative reference so CapCut remains portable.
    """
    if selected:
        explicit = project / Path(selected.replace("\\", "/"))
        if explicit.is_file():
            return selected.replace("\\", "/")
    if kind == "image":
        folder = project / "assets" / "images"
        extensions = (".png", ".jpg", ".jpeg", ".webp")
        stems = (prompt_id, prompt_id.lower(), f"image_{slot_index:03d}", f"IMG{slot_index:03d}")
    else:
        folder = project / "assets" / "broll"
        # The Production Sheet treats both STOCK_VIDEO and STOCK_IMAGE as B-roll slots.
        # Stock stills may therefore live in assets/broll beside video clips and use the
        # same BR001.. identifiers.  Resolve both media families so every stock slot can
        # survive into the Actual Timeline / CapCut V3 track.
        extensions = (".mp4", ".mov", ".m4v", ".webm", ".png", ".jpg", ".jpeg", ".webp")
        stems = (prompt_id, prompt_id.lower(), f"broll_{slot_index:03d}", f"BR{slot_index:03d}")
    if folder.is_dir():
        # Exact/common names first.
        for stem in stems:
            for ext in extensions:
                candidate = folder / f"{stem}{ext}"
                if candidate.is_file():
                    return candidate.relative_to(project).as_posix()
        # Windows is case-insensitive but tests/Linux are not; compare normalized stems.
        wanted = {stem.lower() for stem in stems}
        for candidate in folder.iterdir():
            if candidate.is_file() and candidate.suffix.lower() in extensions and candidate.stem.lower() in wanted:
                return candidate.relative_to(project).as_posix()
    # Preserve legacy placeholder-compatible reference if no real asset is present yet.
    return f"assets/images/image_{slot_index:03d}.png" if kind == "image" else f"assets/broll/broll_{slot_index:03d}.mp4"


def _load_production_assignments(project: Path) -> dict[str, dict[str, str]]:
    """Return visual assignments keyed by scene ID from 07_production_sheet.csv.

    Timing never comes from this file; it contributes only asset assignment metadata.
    """
    path = project / "07_production_sheet.csv"
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise TimelineBuildError(f"Could not read 07_production_sheet.csv: {exc}") from exc
    assignments: dict[str, dict[str, str]] = {}
    image_index = 0
    broll_index = 0
    for row in rows:
        scene_id = str(row.get("scene_id") or row.get("Scene ID") or "").strip()
        asset_type = str(row.get("recommended_asset_type") or row.get("asset_type") or "").strip().upper()
        if not scene_id:
            continue
        if asset_type == "AI_IMAGE":
            prompt_id = str(row.get("image_prompt_id") or "").strip()
            if not prompt_id:
                raise TimelineBuildError(f"Scene {scene_id} is assigned AI_IMAGE but image_prompt_id is missing")
            image_index += 1
            selected = str(row.get("selected_asset_path") or "").strip().replace("\\", "/")
            reference = _discover_production_asset(project, kind="image", prompt_id=prompt_id, slot_index=image_index, selected=selected)
            assignments[scene_id] = {
                "kind": "image",
                "slot_id": f"image_{image_index:03d}",
                "prompt_id": prompt_id,
                "reference": reference,
                "production_asset_type": asset_type,
            }
        elif asset_type in {"STOCK_VIDEO", "STOCK_IMAGE"}:
            prompt_id = str(row.get("broll_prompt_id") or "").strip()
            if not prompt_id:
                raise TimelineBuildError(f"Scene {scene_id} is assigned {asset_type} but broll_prompt_id is missing")
            broll_index += 1
            selected = str(row.get("selected_asset_path") or "").strip().replace("\\", "/")
            reference = _discover_production_asset(project, kind="broll", prompt_id=prompt_id, slot_index=broll_index, selected=selected)
            assignments[scene_id] = {
                "kind": "broll",
                "slot_id": f"broll_{broll_index:03d}",
                "prompt_id": prompt_id,
                "reference": reference,
                "production_asset_type": asset_type,
            }
    return assignments


def _load_base_avatar_timeline(project: Path) -> dict[str, Any] | None:
    """Load authoritative continuous avatar chunk placement from Avatar Timing Sync."""
    path = project / "avatar_timing_manifest.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TimelineBuildError(f"Invalid avatar_timing_manifest.json: {exc}") from exc
    chunks = payload.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise TimelineBuildError("avatar_timing_manifest.json contains no avatar chunks")
    base_chunks: list[dict[str, Any]] = []
    previous_end = None
    for index, item in enumerate(chunks, start=1):
        filename = str(item.get("chunk_filename") or "").strip()
        if not filename:
            raise TimelineBuildError(f"avatar_timing_manifest.json chunk {index} is missing chunk_filename")
        try:
            start = float(item["global_audio_start"])
            end = float(item["global_audio_end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TimelineBuildError(f"avatar_timing_manifest.json chunk {filename} has invalid global timing") from exc
        if start < 0 or end <= start:
            raise TimelineBuildError(f"avatar_timing_manifest.json chunk {filename} has invalid range {start} -> {end}")
        if previous_end is not None and abs(start - previous_end) > 0.000001:
            raise TimelineBuildError(
                f"avatar_timing_manifest.json chunks are not continuous: previous end {previous_end:.6f}, "
                f"{filename} start {start:.6f}"
            )
        previous_end = end
        base_chunks.append({
            "order": index,
            "filename": filename,
            "reference": _normalize_avatar_reference(filename),
            "start_seconds": start,
            "end_seconds": end,
            "duration_seconds": end - start,
        })
    try:
        total = float(payload.get("total_avatar_duration", base_chunks[-1]["end_seconds"]))
    except (TypeError, ValueError) as exc:
        raise TimelineBuildError("avatar_timing_manifest.json has invalid total_avatar_duration") from exc
    if abs(total - base_chunks[-1]["end_seconds"]) > 0.000001:
        raise TimelineBuildError(
            "avatar_timing_manifest total duration does not equal final chunk end: "
            f"{total:.6f} vs {base_chunks[-1]['end_seconds']:.6f}"
        )
    return {
        "source": "avatar_timing_manifest.json",
        "total_duration_seconds": total,
        "chunks": base_chunks,
    }

def build_timeline_manifest(
    project: Path,
    timeline_csv: Path | None = None,
    *,
    duration_tolerance_seconds: float = DEFAULT_DURATION_TOLERANCE_SECONDS,
) -> TimelineBuildResult:
    if duration_tolerance_seconds < 0:
        raise TimelineBuildError("Duration tolerance cannot be negative")
    project = Path(project).resolve()
    timeline_csv = Path(timeline_csv or project / "08_actual_timeline.csv").resolve()
    if not timeline_csv.is_file():
        raise TimelineBuildError("08_actual_timeline.csv is missing")

    try:
        with timeline_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or any(column not in reader.fieldnames for column in REQUIRED_COLUMNS):
                missing = [c for c in REQUIRED_COLUMNS if not reader.fieldnames or c not in reader.fieldnames]
                raise TimelineBuildError("Corrupted CSV or missing columns: " + ", ".join(missing))
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise TimelineBuildError(f"Could not read timeline CSV: {exc}") from exc
    if not rows:
        raise TimelineBuildError("Timeline CSV contains no scenes")

    production_assignments = _load_production_assignments(project)
    base_avatar = _load_base_avatar_timeline(project)
    scenes: list[dict[str, Any]] = []
    warnings: list[str] = []
    previous_start = -1.0
    for index, row in enumerate(rows, start=1):
        scene_id = (row.get("Scene ID") or "").strip()
        try:
            narration = validate_script_text(row.get("Script Text") or "", scene_id).strip()
        except ValueError as exc:
            raise TimelineBuildError(str(exc)) from exc
        avatar_chunk = (row.get("Avatar Chunk") or "").strip()
        if not scene_id:
            raise TimelineBuildError(f"Row {index}: Scene ID is missing")
        if not avatar_chunk:
            raise TimelineBuildError(f"Row {index}: avatar reference is missing")
        start = _timeline_time(row.get("Actual Audio Start", ""), "Actual Audio Start", index)
        end = _timeline_time(row.get("Actual Audio End", ""), "Actual Audio End", index)
        reported_duration = _numeric_seconds(row.get("Duration", ""), "Duration", index)
        if end < start:
            raise TimelineBuildError(f"Row {index}: Actual Audio End must be greater than or equal to Actual Audio Start")
        calculated_duration = end - start
        if calculated_duration <= 0 or reported_duration <= 0:
            raise TimelineBuildError(f"Row {index}: scene duration must be greater than zero")
        duration_delta = abs(calculated_duration - reported_duration)
        if duration_delta > duration_tolerance_seconds:
            raise TimelineBuildError(
                f"Row {index}: Duration differs from Actual Audio Start/End by "
                f"{duration_delta:.3f}s, exceeding tolerance {duration_tolerance_seconds:.3f}s"
            )
        if duration_delta > 0:
            warnings.append(
                f"Row {index}: displayed timing differs from Duration by {duration_delta:.3f}s; "
                "start/end timing was used"
            )
        if start < previous_start:
            raise TimelineBuildError(f"Row {index}: scene timing is not sequential")
        previous_start = start
        avatar_references = _split_avatar_references(avatar_chunk)
        avatar_asset = {"reference": avatar_references[0], "required": True}
        if len(avatar_references) > 1:
            avatar_asset["references"] = avatar_references
        scenes.append({
            "order": index,
            "scene_id": scene_id,
            "narration_text": narration,
            "timing": {
                "start_seconds": start,
                "end_seconds": end,
                "duration_seconds": calculated_duration,
                "reported_duration_seconds": reported_duration,
            },
            "assets": {
                "avatar": avatar_asset,
                "image": None,
                "broll": None,
            },
            "visual_assignment": production_assignments.get(scene_id),
            "transition": {"type": "none", "duration_seconds": 0.0},
            "tracks": {"avatar_video": "V1", "image": "V2", "broll": "V3", "avatar_audio": "A1"},
            "timing_source": (row.get("Timing Source") or "").strip(),
        })

    duration_seconds = max(scene["timing"]["end_seconds"] for scene in scenes)
    manifest: dict[str, Any] = {
        "schema": "senior-health-ai.timeline-manifest",
        "schema_version": SCHEMA_VERSION,
        "project_name": project.name,
        "timebase": {"unit": "seconds", "source": "08_actual_timeline.csv", "recalculation_allowed": False},
        "timeline": {"duration_seconds": duration_seconds, "scene_count": len(scenes)},
        "base_avatar": base_avatar,
        "production_assignments": {
            "source": "07_production_sheet.csv",
            "image_count": sum(1 for item in production_assignments.values() if item["kind"] == "image"),
            "broll_count": sum(1 for item in production_assignments.values() if item["kind"] == "broll"),
        },
        "tracks": [
            {"id": "V1", "kind": "video", "purpose": "avatar"},
            {"id": "V2", "kind": "video", "purpose": "images"},
            {"id": "V3", "kind": "video", "purpose": "broll"},
            {"id": "A1", "kind": "audio", "purpose": "avatar_audio"},
        ],
        "scenes": scenes,
    }
    manifest["content_sha256"] = _stable_hash(manifest)
    out = project / "capcut" / "timeline_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return TimelineBuildResult(True, out, len(scenes), duration_seconds, warnings)


def load_timeline_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TimelineBuildError(f"Invalid timeline manifest: {exc}") from exc
    if data.get("schema") != "senior-health-ai.timeline-manifest" or not isinstance(data.get("scenes"), list):
        raise TimelineBuildError("Unsupported timeline manifest schema")
    return data
