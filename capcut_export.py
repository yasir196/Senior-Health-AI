from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from timeline_builder import TimelineBuildError, load_timeline_manifest
from text_overlay import ARTIFACT_NAME, DEFAULT_TEXT_OVERLAY_STYLE, load_artifact, visual_text

SUPPORTED_CAPCUT_SCHEMA = "CapCut Desktop 8.7 Windows multi-file draft layout"
CAPCUT_APP_VERSION = "8.7.0"
CAPCUT_NATIVE_NEW_VERSION = "171.0.0"
CAPCUT_SCHEMA_VERSION = 360000
CAPCUT_87_ROOT_JSON_FILES = (
    "draft_agency_config.json",
    "draft_biz_config.json",
    "attachment_pc_common.json",
    "performance_opt_info.json",
)
CAPCUT_87_AUXILIARY_DIRS = (
    "Resources", "Timelines", "subdraft", "adjust_mask", "common_attachment",
    "matting", "smart_crop", "qr_upload",
)
NAMESPACE = uuid.UUID("790e21bb-40d1-4af2-b9d0-92fcb6a6e5bf")

class CapCutExportError(ValueError):
    pass

@dataclass(frozen=True)
class CapCutExportResult:
    success: bool
    project_dir: Path
    scenes: int
    duration_seconds: float
    missing_assets: list[str]
    warnings: list[str]


def _id(key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, key))


def _us(seconds: float) -> int:
    return int(round(float(seconds) * 1_000_000))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _clip() -> dict[str, Any]:
    return {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False}, "rotation": 0.0,
            "scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": 0.0}}


def _video_material(mid: str, path: Path, *, photo: bool, name: str, duration_us: int) -> dict[str, Any]:
    return {"id": mid, "type": "photo" if photo else "video", "name": name, "path": str(path),
            "duration": duration_us, "width": 1920, "height": 1080, "has_audio": not photo,
            "material_name": name, "category_name": "local", "local_material_id": mid}


def _segment(sid: str, mid: str, start_us: int, duration_us: int, *, source_start_us: int = 0, muted: bool = False) -> dict[str, Any]:
    return {"id": sid, "material_id": mid, "target_timerange": {"start": start_us, "duration": duration_us},
            "source_timerange": {"start": source_start_us, "duration": duration_us}, "extra_material_refs": [],
            "clip": _clip(), "volume": 0.0 if muted else 1.0, "visible": True}



def _text_material(mid: str, content: str, style: dict[str, Any]) -> dict[str, Any]:
    """Minimum native CapCut 8.7 text material used by the dedicated overlay track."""
    return {
        "id": mid, "type": "text", "name": "Text Overlay", "content": content,
        "font_name": str(style.get("font_family", "Arial")),
        "font_size": float(style.get("font_size", 14.0)),
        "bold": bool(style.get("bold", True)), "italic": bool(style.get("italic", False)),
        "alignment": int(style.get("alignment", 1)),
        "text_color": str(style.get("text_color", "#FFFFFF")),
        "stroke": {"on": True, "color": str(style.get("stroke_color", "#000000")), "width": float(style.get("stroke_width", 0.08))},
        "shadow": {"on": bool(style.get("shadow", True))},
        "typesetting": 0, "text_size": {"width": 0.0, "height": 0.0},
    }

def _text_segment(sid: str, mid: str, start_us: int, duration_us: int, style: dict[str, Any]) -> dict[str, Any]:
    segment = _segment(sid, mid, start_us, duration_us)
    segment["clip"]["transform"] = {"x": float(style.get("transform_x", -0.43)), "y": float(style.get("transform_y", 0.27))}
    segment["track_render_index"] = 100
    return segment

AI_IMAGE_ZOOM_SCALE = 1.08


def _capcut_keyframe_entry(
    frame_id: str,
    time_offset_us: int,
    value: float,
    *,
    curve_type: str = "Line",
    right_control: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Return the CapCut Desktop 8.7 common-keyframe entry shape."""
    return {
        "curveType": curve_type,
        "graphID": "",
        "id": frame_id,
        "left_control": {"x": 0.0, "y": 0.0},
        "right_control": right_control or {"x": 0.0, "y": 0.0},
        "string_value": "",
        "time_offset": int(time_offset_us),
        "values": [float(value)],
    }


def _image_zoom_keyframes(segment_id: str, duration_us: int, *, zoom_in: bool) -> list[dict[str, Any]]:
    """Return CapCut 8.7 native scale keyframes for one AI-image segment.

    CapCut Desktop 8.7 represents locked/uniform video scale as a ``KFTypeScaleX``
    common-keyframe lane while ``segment.uniform_scale.on`` is true.  The previous
    exporter wrote the non-native ``KFTypeUniformScale`` property, which CapCut
    could preserve in JSON but silently ignore during playback.  ``time_offset``
    is clip-relative microseconds, so timeline/source timeranges remain untouched.
    """
    if duration_us <= 0:
        raise CapCutExportError("AI-image zoom requires a positive segment duration")
    start_scale, end_scale = (1.0, AI_IMAGE_ZOOM_SCALE) if zoom_in else (AI_IMAGE_ZOOM_SCALE, 1.0)
    keyframe_group_id = _id(f"{segment_id}:keyframes:scale-x")

    # Real CapCut Desktop 8.7 reference (5,000,000 us, 1.00 -> 1.08) writes
    # the opening keyframe as FreeCurveInOut with right_control x=1,600,000
    # (32% of clip duration) and y=0.0752 (94% of the scale delta).  Preserve
    # those native proportions for any actual image-segment duration.
    delta = end_scale - start_scale
    opening_right_control = {
        "x": float(duration_us) * 0.32,
        "y": float(delta) * 0.94,
    }
    return [{
        "id": keyframe_group_id,
        "material_id": "",
        "property_type": "KFTypeScaleX",
        "keyframe_list": [
            _capcut_keyframe_entry(
                _id(f"{keyframe_group_id}:start"), 0, start_scale,
                curve_type="FreeCurveInOut", right_control=opening_right_control,
            ),
            _capcut_keyframe_entry(_id(f"{keyframe_group_id}:end"), duration_us, end_scale),
        ],
    }]


def _apply_image_zoom(segment: dict[str, Any], *, image_assignment_index: int) -> None:
    """Apply deterministic alternating native CapCut scale motion to an AI image only."""
    if image_assignment_index <= 0:
        raise CapCutExportError("AI-image assignment index must be positive")
    duration_us = int(segment["target_timerange"]["duration"])
    zoom_in = image_assignment_index % 2 == 1
    end_scale = AI_IMAGE_ZOOM_SCALE if zoom_in else 1.0
    # Match the native CapCut 8.7 segment state around common_keyframes.  The
    # manual reference keeps keyframe_refs as an explicit empty list and stores
    # clip.scale at the final evaluated keyframe value, not at frame zero.
    segment["uniform_scale"] = {"on": True, "value": 1.0}
    segment["keyframe_refs"] = []
    segment["clip"]["scale"] = {"x": end_scale, "y": end_scale}
    segment["common_keyframes"] = _image_zoom_keyframes(segment["id"], duration_us, zoom_in=zoom_in)



TEXT_OVERLAY_TEMPLATE_DIR = Path(__file__).resolve().parent / "Templates" / "capcut_text_overlay"
TEXT_OVERLAY_REFERENCE_JSON = TEXT_OVERLAY_TEMPLATE_DIR / "compound_reference.json"
TEXT_OVERLAY_SUBDRAFT_CONFIG = TEXT_OVERLAY_TEMPLATE_DIR / "sub_draft_config.json"
TEXT_OVERLAY_DRAFT_COVER = TEXT_OVERLAY_TEMPLATE_DIR / "draft_cover.jpg"

EVIDENCE_OVERLAY_TEMPLATE_DIR = Path(__file__).resolve().parent / "Templates" / "capcut_evidence_overlay"
EVIDENCE_OVERLAY_REFERENCE_JSON = EVIDENCE_OVERLAY_TEMPLATE_DIR / "compound_reference.json"
EVIDENCE_OVERLAY_SUBDRAFT_CONFIG = EVIDENCE_OVERLAY_TEMPLATE_DIR / "sub_draft_config.json"
EVIDENCE_OVERLAY_DRAFT_COVER = EVIDENCE_OVERLAY_TEMPLATE_DIR / "draft_cover.jpg"
EVIDENCE_DISALLOWED_SOURCE_PATHS = ("C:/Users/Dell/AppData/", "D:/capcuts/")

# Visual-polish profile for the live-verified compound Text Overlay.  Overlay
# Type is metadata for styling only; it never changes text/timing/animation.
TEXT_OVERLAY_TYPE_STYLES = {
    # High-contrast Text Overlay palette.  Background determines the main
    # text color; no other CapCut geometry/timing/template behavior changes.
    "NUMBER": {"background": "#FFD400", "text": "#000000", "accent": "#000000"},
    "TAKEAWAY": {"background": "#FFD400", "text": "#000000", "accent": "#000000"},
    "MYTH CHECK": {"background": "#FF3B30", "text": "#FFFFFF", "accent": "#FFFFFF"},
    "SAFETY": {"background": "#FF3B30", "text": "#FFFFFF", "accent": "#FFFFFF"},
    "KEY FACT": {"background": "#000000", "text": "#FFD400", "accent": "#FFFFFF"},
    "CONTRAST": {"background": "#000000", "text": "#FFFFFF", "accent": "#FFD400"},
    "ACTION": {"background": "#000000", "text": "#FFD400", "accent": "#FFFFFF"},
}
TEXT_OVERLAY_DEFAULT_STYLE = {"background": "#000000", "text": "#FFFFFF", "accent": "#FFD400"}
TEXT_OVERLAY_BACKGROUND_OPACITY = 0.75


def _hex_rgb01(value: str) -> list[float]:
    value = str(value).strip().lstrip("#")
    if len(value) != 6:
        raise CapCutExportError(f"Invalid Text Overlay color: {value!r}")
    return [int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def _overlay_style(overlay_type: str) -> dict[str, str]:
    return TEXT_OVERLAY_TYPE_STYLES.get(
        str(overlay_type or "").strip().upper(),
        TEXT_OVERLAY_DEFAULT_STYLE,
    )


def _overlay_accent(overlay_type: str) -> str:
    return _overlay_style(overlay_type)["accent"]


def _fresh_uuid() -> str:
    return str(uuid.uuid4()).upper()


def _remap_reference_uuids(payload: Any) -> tuple[Any, dict[str, str]]:
    """Deep-clone a live-verified CapCut payload and replace every UUID."""
    import re
    uuid_re = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
    raw = json.dumps(payload, ensure_ascii=False)
    old_ids = sorted(set(uuid_re.findall(raw)))
    mapping = {old: _fresh_uuid() for old in old_ids}
    for old, new in mapping.items():
        raw = re.sub(re.escape(old), new, raw, flags=re.I)
    return json.loads(raw), mapping


def _load_compound_overlay_reference() -> dict[str, Any]:
    required = (TEXT_OVERLAY_REFERENCE_JSON, TEXT_OVERLAY_SUBDRAFT_CONFIG, TEXT_OVERLAY_DRAFT_COVER)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise CapCutExportError("Missing live-verified Text Overlay template file(s): " + ", ".join(missing))
    return json.loads(TEXT_OVERLAY_REFERENCE_JSON.read_text(encoding="utf-8"))


def _load_evidence_overlay_master() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the sanitized Evidence master exactly once for one export invocation."""
    required = (EVIDENCE_OVERLAY_REFERENCE_JSON, EVIDENCE_OVERLAY_SUBDRAFT_CONFIG, EVIDENCE_OVERLAY_DRAFT_COVER)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise CapCutExportError("Missing sanitized Evidence Overlay template file(s): " + ", ".join(missing))
    raw = EVIDENCE_OVERLAY_REFERENCE_JSON.read_text(encoding="utf-8")
    normalized = raw.replace("\\", "/")
    for forbidden in EVIDENCE_DISALLOWED_SOURCE_PATHS:
        if forbidden in normalized:
            raise CapCutExportError(f"Sanitized Evidence Overlay template retains machine-specific path: {forbidden}")
    reference = json.loads(raw)
    if os.name == "nt":
        required_fonts = (
            Path("C:/Windows/Fonts/Figtree-Bold.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/impact.ttf"),
        )
        missing_fonts = [str(path) for path in required_fonts if not path.is_file()]
        if missing_fonts:
            raise CapCutExportError("Evidence Overlay required font(s) missing: " + ", ".join(missing_fonts))
    config = json.loads(EVIDENCE_OVERLAY_SUBDRAFT_CONFIG.read_text(encoding="utf-8"))
    return reference, config


def _find_evidence_compound_chain(reference: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Locate parent → OUTER(body/heading) → INNER(separator) Evidence graph."""
    parent_segment, outer_combo, outer_draft, inner_segment, inner_combo = _find_compound_chain(reference)
    outer_texts = outer_draft.get("materials", {}).get("texts", [])
    heading = next((m for m in outer_texts if m.get("font_path") == "C:/Windows/Fonts/Figtree-Bold.ttf"), None)
    body = next((m for m in outer_texts if m.get("font_path") == "C:/Windows/Fonts/arial.ttf"), None)
    inner_texts = inner_combo.get("draft", {}).get("materials", {}).get("texts", [])
    separator = next((m for m in inner_texts if m.get("font_path") == "C:/Windows/Fonts/impact.ttf"), None)
    if heading is None or body is None or separator is None:
        raise CapCutExportError("Sanitized Evidence Overlay heading/body/separator material is malformed")
    return parent_segment, outer_combo, outer_draft, inner_segment, inner_combo, heading, body


def _replace_rich_text_exact(material: dict[str, Any], expected_font: str, text: str, label: str) -> None:
    if material.get("font_path") != expected_font:
        raise CapCutExportError(f"Evidence {label} font path mismatch: {material.get('font_path')!r}")
    try:
        rich = json.loads(material["content"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CapCutExportError(f"Evidence {label} rich-text content is malformed") from exc
    rich["text"] = text
    styles = rich.get("styles", [])
    if not styles:
        raise CapCutExportError(f"Evidence {label} has no rich-text style")
    for style in styles:
        style["range"] = [0, len(text)]
        font = style.setdefault("font", {})
        font["path"] = expected_font
    material["content"] = json.dumps(rich, ensure_ascii=False, separators=(",", ":"))


def _evidence_body_text(row: dict[str, Any]) -> str:
    bullets = [str(row.get(f"bullet_{i}", "")) for i in range(1, 4)]
    if any(not x.strip() for x in bullets):
        raise CapCutExportError(f"Evidence overlay {row.get('overlay_id')} requires exactly 3 non-empty bullets")
    return "\n".join(f"• {value}" for value in bullets)


def _assert_resolved_overlay_schedule(rows: list[dict[str, Any]]) -> None:
    """Phase 3 trusts Phase 1/2 scheduling but hard-fails if its invariant is violated."""
    active = [r for r in rows if str(r.get("status", "")).upper() in {"READY", "WARNING"}]
    normalized = []
    for row in active:
        cls = str(row.get("overlay_class", "STANDARD")).upper() or "STANDARD"
        start = float(row.get("start_seconds", 0))
        end = float(row.get("end_seconds", start + float(row.get("duration_seconds", 0))))
        if end <= start:
            raise CapCutExportError(f"Overlay {row.get('overlay_id')} has non-positive canonical interval")
        normalized.append((row, cls, start, end))
    for i, (a, ac, a0, a1) in enumerate(normalized):
        for b, bc, b0, b1 in normalized[i + 1:]:
            if max(a0, b0) < min(a1, b1) and ({ac, bc} == {"STANDARD", "EVIDENCE"} or ac == bc == "EVIDENCE"):
                raise CapCutExportError(
                    "Unified overlay schedule collision survived Phase 1/2: "
                    f"{a.get('overlay_id')}[{ac}] vs {b.get('overlay_id')}[{bc}]"
                )


def _find_compound_chain(reference: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Locate the proven two-level compound chain without hard-coding reference UUIDs."""
    drafts = reference.get("materials", {}).get("drafts", [])
    draft_ids = {d["id"] for d in drafts}
    for track in reference.get("tracks", []):
        if track.get("type") != "video":
            continue
        for segment in track.get("segments", []):
            outer_ids = [x for x in segment.get("extra_material_refs", []) if x in draft_ids]
            if not outer_ids:
                continue
            outer_combo = next(d for d in drafts if d["id"] == outer_ids[0])
            outer_draft = outer_combo["draft"]
            for inner_track in outer_draft.get("tracks", []):
                if inner_track.get("type") != "video":
                    continue
                for inner_segment in inner_track.get("segments", []):
                    inner_ids = [x for x in inner_segment.get("extra_material_refs", []) if x in draft_ids]
                    if inner_ids:
                        inner_combo = next(d for d in drafts if d["id"] == inner_ids[0])
                        return segment, outer_combo, outer_draft, inner_segment, inner_combo
    raise CapCutExportError("Live-verified Text Overlay compound chain was not found in template")


def _set_compound_duration(draft: dict[str, Any], duration_us: int) -> None:
    draft["duration"] = duration_us
    for track in draft.get("tracks", []):
        for segment in track.get("segments", []):
            target = segment.get("target_timerange")
            if isinstance(target, dict):
                target["duration"] = duration_us
            source = segment.get("source_timerange")
            if isinstance(source, dict):
                source["duration"] = duration_us
    for video in draft.get("materials", {}).get("videos", []):
        if isinstance(video, dict) and "duration" in video:
            video["duration"] = duration_us


def _visible_text_from_overlay_value(value: str) -> str:
    """Return plain visible text, unwrapping one accidental rich-text JSON layer.

    CapCut stores a rich-text object as a JSON STRING in material["content"].
    If an already-serialized rich-text payload reaches this helper, only its
    parsed ["text"] field is visible text; assigning the full payload to
    parsed_content["text"] makes CapCut render the JSON literally.
    """
    text = str(value)
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("text"), str):
            text = parsed["text"]
    # Preserve intended line breaks while removing accidental whitespace directly
    # around the break (the manually-created reference contains one such space).
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    suspicious = text.lstrip()
    if suspicious.startswith('{"text":') or suspicious.startswith('{\\\"text\\\":') or suspicious.startswith('{"styles":'):
        raise CapCutExportError("Nested Text Overlay visible text still contains a serialized rich-text payload")
    return text


def _validate_nested_text_materials(text_draft: dict[str, Any], *, expected_main_text: str) -> None:
    """Validate final CapCut nested text content semantics before serialization."""
    materials = text_draft.get("materials", {}).get("texts", [])
    main = next((m for m in materials if m.get("font_path") == "C:/Windows/Fonts/Figtree-Bold.ttf"), None)
    if main is None:
        raise CapCutExportError("Figtree Bold main text material missing during nested-text validation")
    separator = next((m for m in materials if m.get("id") != main.get("id")), None)
    if separator is None:
        raise CapCutExportError("Decorative separator material missing during nested-text validation")

    def parse(material: dict[str, Any], label: str) -> dict[str, Any]:
        raw = material.get("content")
        if not isinstance(raw, str):
            raise CapCutExportError(f"{label} material content is not a JSON string")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CapCutExportError(f"{label} material content is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict) or not isinstance(parsed.get("text"), str):
            raise CapCutExportError(f"{label} material content must parse to an object with string text")
        visible = parsed["text"].lstrip()
        if visible.startswith('{"text":') or visible.startswith('{\\\"text\\\":') or visible.startswith('{"styles":'):
            raise CapCutExportError(f"{label} material visible text contains serialized rich-text JSON")
        return parsed

    main_body = parse(main, "Figtree main text")
    separator_body = parse(separator, "separator")

    # CapCut Desktop 8.7 live validation proved that these native text materials
    # require their physical system-font paths. Keep both the material-level
    # path and the rich-text style path synchronized; font_name alone is not a
    # valid replacement for this live-verified contract.
    expected_fonts = (
        (main, main_body, "C:/Windows/Fonts/Figtree-Bold.ttf", "Figtree main text"),
        (separator, separator_body, "C:/Windows/Fonts/impact.ttf", "separator"),
    )
    for material, body, expected_path, label in expected_fonts:
        if material.get("font_path") != expected_path:
            raise CapCutExportError(
                f"{label} material font_path must preserve native CapCut 8.7 path: {expected_path}"
            )
        for style in body.get("styles", []):
            font = style.get("font")
            if not isinstance(font, dict) or font.get("path") != expected_path:
                raise CapCutExportError(
                    f"{label} rich-text font path must match material font_path: {expected_path}"
                )

    if main_body["text"] != expected_main_text:
        raise CapCutExportError(
            "Figtree main text serialization mismatch: "
            f"expected={expected_main_text!r}, actual={main_body['text']!r}"
        )
    if separator_body["text"] != "------------------------":
        raise CapCutExportError(
            f"Separator serialization mismatch: {separator_body['text']!r}"
        )
    for style in main_body.get("styles", []):
        if style.get("range") != [0, len(expected_main_text)]:
            raise CapCutExportError(
                "Figtree style range does not match visible text length: "
                f"{style.get('range')} vs {len(expected_main_text)}"
            )


def _apply_text_overlay_visual_style(text_draft: dict[str, Any], overlay_type: str) -> None:
    """Apply fixed manual colors to the proven Text Overlay template."""
    materials = text_draft.get("materials", {}).get("texts", [])
    main = next((m for m in materials if m.get("font_path") == "C:/Windows/Fonts/Figtree-Bold.ttf"), None)
    separator = next((m for m in materials if m.get("font_path") == "C:/Windows/Fonts/impact.ttf"), None)
    if main is None or separator is None:
        raise CapCutExportError("Live-verified Figtree/Impact Text Overlay materials are missing")

    style_map = _overlay_style(overlay_type)
    background_color = style_map["background"]
    main_color = style_map["text"]

    # Main visible text: force both CapCut color representations.
    main["text_color"] = main_color.lower()
    main["global_alpha"] = 1.0
    main["text_alpha"] = 1.0
    main_body = json.loads(main["content"])
    main_rgb = _hex_rgb01(main_color)
    for rich_style in main_body.get("styles", []):
        rich_style.setdefault("fill", {}).setdefault("content", {}).setdefault("solid", {})["color"] = main_rgb
    main["content"] = json.dumps(main_body, ensure_ascii=False, separators=(",", ":"))

    # In the supplied template the oversized Impact separator is the visible card.
    # Do NOT recolor canvas materials: they are not the card.
    separator["background_color"] = background_color.lower()
    separator["background_alpha"] = 1.0
    separator["global_alpha"] = 1.0
    separator["text_alpha"] = 1.0

    # Hide the separator dashes by matching their color to the card.
    separator["text_color"] = background_color.lower()
    separator_body = json.loads(separator["content"])
    bg_rgb = _hex_rgb01(background_color)
    for rich_style in separator_body.get("styles", []):
        rich_style.setdefault("fill", {}).setdefault("content", {}).setdefault("solid", {})["color"] = bg_rgb
    separator["content"] = json.dumps(separator_body, ensure_ascii=False, separators=(",", ":"))

def _replace_main_figtree_text(text_draft: dict[str, Any], content: str) -> tuple[str, str]:
    materials = text_draft.get("materials", {}).get("texts", [])
    main = next((m for m in materials if m.get("font_path") == "C:/Windows/Fonts/Figtree-Bold.ttf"), None)
    if main is None:
        raise CapCutExportError("Figtree Bold main text material missing from live-verified template")
    visible_text = _visible_text_from_overlay_value(content)
    body = json.loads(main["content"])
    body["text"] = visible_text
    for style in body.get("styles", []):
        style["range"] = [0, len(visible_text)]
    main["content"] = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    _validate_nested_text_materials(text_draft, expected_main_text=visible_text)
    main_segment = next(
        (s for t in text_draft.get("tracks", []) if t.get("type") == "text"
         for s in t.get("segments", []) if s.get("material_id") == main["id"]), None
    )
    if main_segment is None:
        raise CapCutExportError("Figtree Bold text segment missing from live-verified template")
    return main_segment["id"], main["id"]


def _rewrite_subdraft_config(template: dict[str, Any], *, draft: dict[str, Any], duration_us: int) -> dict[str, Any]:
    """Preserve the real 8.7 config schema; rewrite only generated identity/timing/name fields."""
    cfg = json.loads(json.dumps(template))
    cfg["id"] = draft["id"]
    cfg["project_id"] = draft["id"]
    cfg["name"] = draft.get("name", cfg.get("name", ""))
    cfg["rough_cut_duration"] = duration_us
    cfg["rough_cut_start"] = 0
    cfg["draft_json_file"] = "draft_content.json"
    cfg["cover_path"] = "draft_cover.jpg"
    return cfg



@dataclass(frozen=True)
class GeneratedSubdraftRecord:
    overlay_id: str
    overlay_number: str
    compound_level: str
    subdraft_id: str
    physical_directory: Path
    draft_content_path: Path
    config_path: Path
    cover_path: Path
    metadata_draft_path: str
    metadata_config_path: str
    metadata_cover_path: str


def _capcut_placeholder_path(placeholder: str, subdraft_id: str, filename: str) -> str:
    """Return the native CapCut draft-root placeholder path used by the real 8.7 reference."""
    return f"{placeholder}\\subdraft\\{subdraft_id}\\{filename}"


def _windows_long_io_path(path: Path) -> str:
    """Return an extended-length Win32 path for physical I/O only.

    CapCut JSON keeps its native draft-root placeholder path. This helper is only
    for Python filesystem operations so long selected-project paths do not hit
    classic MAX_PATH.
    """
    raw = str(Path(path).resolve())
    if os.name != "nt":
        return raw
    if raw.startswith("\\\\?\\"):
        return raw
    if raw.startswith("\\\\"):
        return "\\\\?\\UNC\\" + raw.lstrip("\\")
    return "\\\\?\\" + raw


def _write_subdraft_json(path: Path, payload: Any) -> None:
    _mkdir_long_safe(path.parent)
    io_path = _windows_long_io_path(path)
    with open(io_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _copy_subdraft_cover(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_windows_long_io_path(source), _windows_long_io_path(destination))


def _path_is_file_long_safe(path: Path) -> bool:
    try:
        return os.path.isfile(_windows_long_io_path(path))
    except OSError:
        return False


def _validate_generated_subdraft_record(record: GeneratedSubdraftRecord) -> None:
    required = (
        ("draft_content.json", record.draft_content_path),
        ("sub_draft_config.json", record.config_path),
        ("draft_cover.jpg", record.cover_path),
    )
    for label, path in required:
        if not _path_is_file_long_safe(path):
            raise CapCutExportError(
                "Text Overlay physical subdraft integrity failure: "
                f"overlay_number={record.overlay_number}, overlay_id={record.overlay_id}, "
                f"compound_level={record.compound_level}, subdraft_id={record.subdraft_id}, "
                f"missing_file={label}, path={path}"
            )


def _build_compound_overlay(
    *,
    overlay_row: dict[str, Any],
    draft_dir: Path,
    draft_path_placeholder: str,
) -> dict[str, Any]:
    """Clone one complete live-verified two-level CapCut 8.7 compound overlay."""
    reference = _load_compound_overlay_reference()
    cloned, _ = _remap_reference_uuids(reference)
    parent_segment, outer_combo, outer_draft, inner_segment, inner_combo = _find_compound_chain(cloned)

    start_us = _us(overlay_row["start_seconds"])
    duration_us = _us(overlay_row["duration_seconds"])
    if duration_us <= 0:
        raise CapCutExportError(f"Text overlay {overlay_row['overlay_id']} has non-positive duration")

    # Authoritative overlay timing affects only the parent placement; nested clips
    # run from zero for exactly the same duration.
    parent_segment["target_timerange"]["start"] = start_us
    parent_segment["target_timerange"]["duration"] = duration_us
    if isinstance(parent_segment.get("source_timerange"), dict):
        parent_segment["source_timerange"]["start"] = 0
        parent_segment["source_timerange"]["duration"] = duration_us

    _set_compound_duration(outer_draft, duration_us)
    inner_segment["target_timerange"]["start"] = 0
    inner_segment["target_timerange"]["duration"] = duration_us
    if isinstance(inner_segment.get("source_timerange"), dict):
        inner_segment["source_timerange"]["start"] = 0
        inner_segment["source_timerange"]["duration"] = duration_us

    text_draft = inner_combo["draft"]
    _set_compound_duration(text_draft, duration_us)
    rendered = visual_text(str(overlay_row["overlay_text"]))
    main_segment_id, main_material_id = _replace_main_figtree_text(text_draft, rendered)
    _apply_text_overlay_visual_style(text_draft, str(overlay_row.get("overlay_type", "")))

    # The two combination materials remain in root materials.drafts exactly as in
    # the live-verified reference. Each also gets a physical subdraft payload.
    config_template = json.loads(TEXT_OVERLAY_SUBDRAFT_CONFIG.read_text(encoding="utf-8"))
    subdraft_records: list[GeneratedSubdraftRecord] = []
    overlay_number = str(overlay_row.get("overlay_number", ""))
    for compound_level, combo in (("OUTER", outer_combo), ("INNER", inner_combo)):
        subdraft_id = _fresh_uuid()
        subdir = draft_dir / "subdraft" / subdraft_id
        draft_file = subdir / "draft_content.json"
        config_file = subdir / "sub_draft_config.json"
        cover_file = subdir / "draft_cover.jpg"

        record = GeneratedSubdraftRecord(
            overlay_id=str(overlay_row["overlay_id"]),
            overlay_number=overlay_number,
            compound_level=compound_level,
            subdraft_id=subdraft_id,
            physical_directory=subdir,
            draft_content_path=draft_file,
            config_path=config_file,
            cover_path=cover_file,
            metadata_draft_path=_capcut_placeholder_path(
                draft_path_placeholder, subdraft_id, "draft_content.json"
            ),
            metadata_config_path=_capcut_placeholder_path(
                draft_path_placeholder, subdraft_id, "sub_draft_config.json"
            ),
            metadata_cover_path=_capcut_placeholder_path(
                draft_path_placeholder, subdraft_id, "draft_cover.jpg"
            ),
        )

        # The same authoritative record drives BOTH JSON metadata and disk I/O.
        combo["draft_file_path"] = record.metadata_draft_path
        combo["draft_config_path"] = record.metadata_config_path
        combo["draft_cover_path"] = record.metadata_cover_path

        try:
            _write_subdraft_json(record.draft_content_path, combo["draft"])
            _write_subdraft_json(
                record.config_path,
                _rewrite_subdraft_config(config_template, draft=combo["draft"], duration_us=duration_us),
            )
            _copy_subdraft_cover(TEXT_OVERLAY_DRAFT_COVER, record.cover_path)
        except (FileNotFoundError, OSError) as exc:
            raise CapCutExportError(
                "Text Overlay physical subdraft write failed: "
                f"overlay_number={record.overlay_number}, overlay_id={record.overlay_id}, "
                f"compound_level={record.compound_level}, subdraft_id={record.subdraft_id}, "
                f"draft_content_path={record.draft_content_path}, "
                f"config_path={record.config_path}, cover_path={record.cover_path}; "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        _validate_generated_subdraft_record(record)
        subdraft_records.append(record)

    # Root companion materials referenced by the parent segment.
    root_materials = cloned["materials"]
    parent_video = next(v for v in root_materials.get("videos", []) if v["id"] == parent_segment["material_id"])
    parent_video["duration"] = duration_us

    companion_keys = (
        "canvases", "material_animations", "placeholder_infos", "speeds",
        "sound_channel_mappings", "material_colors", "vocal_separations",
    )
    companions = {key: [] for key in companion_keys}
    parent_refs = set(parent_segment.get("extra_material_refs", []))
    for key in companion_keys:
        companions[key] = [item for item in root_materials.get(key, []) if item.get("id") in parent_refs]

    return {
        "overlay_id": str(overlay_row["overlay_id"]),
        "overlay_number": str(overlay_row.get("overlay_number", "")),
        "start_us": start_us,
        "duration_us": duration_us,
        "parent_segment": parent_segment,
        "parent_video": parent_video,
        "outer_combo": outer_combo,
        "inner_combo": inner_combo,
        "outer_nested_draft_id": outer_draft["id"],
        "inner_parent_segment_id": inner_segment["id"],
        "text_nested_draft_id": text_draft["id"],
        "main_text_segment_id": main_segment_id,
        "main_text_material_id": main_material_id,
        "companions": companions,
        "subdrafts": subdraft_records,
    }


def _build_evidence_compound(
    *,
    overlay_row: dict[str, Any],
    evidence_master: dict[str, Any],
    config_template: dict[str, Any],
    draft_dir: Path,
    draft_path_placeholder: str,
) -> dict[str, Any]:
    """Render one verified Evidence row by deep-cloning the sanitized master."""
    cloned, _ = _remap_reference_uuids(evidence_master)
    parent_segment, outer_combo, outer_draft, inner_segment, inner_combo, heading_material, body_material = _find_evidence_compound_chain(cloned)
    text_draft = inner_combo["draft"]

    start_us = _us(overlay_row["start_seconds"])
    duration_us = _us(overlay_row["duration_seconds"])
    end_us = _us(overlay_row["end_seconds"])
    if duration_us <= 0 or end_us - start_us != duration_us:
        raise CapCutExportError(f"Evidence overlay {overlay_row.get('overlay_id')} canonical timing is inconsistent")

    parent_segment["target_timerange"] = {"start": start_us, "duration": duration_us}
    if isinstance(parent_segment.get("source_timerange"), dict):
        parent_segment["source_timerange"] = {"start": 0, "duration": duration_us}
    _set_compound_duration(outer_draft, duration_us)
    inner_segment["target_timerange"] = {"start": 0, "duration": duration_us}
    if isinstance(inner_segment.get("source_timerange"), dict):
        inner_segment["source_timerange"] = {"start": 0, "duration": duration_us}
    _set_compound_duration(text_draft, duration_us)

    # Preserve reference entrance keyframes, but no keyframe may extend beyond the canonical duration.
    for lane in inner_segment.get("common_keyframes", []):
        for frame in lane.get("keyframe_list", []):
            if int(frame.get("time_offset", 0)) > duration_us:
                raise CapCutExportError(
                    f"Evidence overlay {overlay_row.get('overlay_id')} is shorter than its preserved entrance animation"
                )

    heading = str(overlay_row.get("heading", ""))
    if not heading.strip():
        raise CapCutExportError(f"Evidence overlay {overlay_row.get('overlay_id')} heading is empty")
    body_text = _evidence_body_text(overlay_row)
    _replace_rich_text_exact(heading_material, "C:/Windows/Fonts/Figtree-Bold.ttf", heading, "heading")
    _replace_rich_text_exact(body_material, "C:/Windows/Fonts/arial.ttf", body_text, "body")

    # Sanitation contract: full-frame canvas materials are explicitly white and local cached effects/audio are absent.
    for nested in (cloned, outer_draft, text_draft):
        for canvas in nested.get("materials", {}).get("canvases", []):
            if canvas.get("type") == "canvas_color":
                canvas["color"] = "#ffffff"

    subdraft_records: list[GeneratedSubdraftRecord] = []
    overlay_number = str(overlay_row.get("overlay_number", ""))
    # Allocate both physical destinations first so OUTER can point at the generated INNER.
    pairs = []
    for compound_level, combo in (("OUTER", outer_combo), ("INNER", inner_combo)):
        subdraft_id = _fresh_uuid()
        subdir = draft_dir / "subdraft" / subdraft_id
        record = GeneratedSubdraftRecord(
            overlay_id=str(overlay_row["overlay_id"]), overlay_number=overlay_number, compound_level=compound_level,
            subdraft_id=subdraft_id, physical_directory=subdir, draft_content_path=subdir / "draft_content.json",
            config_path=subdir / "sub_draft_config.json", cover_path=subdir / "draft_cover.jpg",
            metadata_draft_path=_capcut_placeholder_path(draft_path_placeholder, subdraft_id, "draft_content.json"),
            metadata_config_path=_capcut_placeholder_path(draft_path_placeholder, subdraft_id, "sub_draft_config.json"),
            metadata_cover_path=_capcut_placeholder_path(draft_path_placeholder, subdraft_id, "draft_cover.jpg"),
        )
        combo["draft_file_path"] = record.metadata_draft_path
        combo["draft_config_path"] = record.metadata_config_path
        combo["draft_cover_path"] = record.metadata_cover_path
        pairs.append((combo, record))

    # The raw reference omitted INNER's physical folder. Generated OUTER embeds the INNER material with its fresh paths.
    outer_payload = json.loads(json.dumps(outer_combo["draft"]))
    outer_payload.setdefault("materials", {})["drafts"] = [json.loads(json.dumps(inner_combo))]
    inner_payload = inner_combo["draft"]
    payload_by_level = {"OUTER": outer_payload, "INNER": inner_payload}

    for combo, record in pairs:
        payload = payload_by_level[record.compound_level]
        try:
            _write_subdraft_json(record.draft_content_path, payload)
            _write_subdraft_json(record.config_path, _rewrite_subdraft_config(config_template, draft=payload, duration_us=duration_us))
            _copy_subdraft_cover(EVIDENCE_OVERLAY_DRAFT_COVER, record.cover_path)
        except (FileNotFoundError, OSError) as exc:
            raise CapCutExportError(
                f"Evidence Overlay physical subdraft write failed: overlay_id={record.overlay_id}, "
                f"compound_level={record.compound_level}, subdraft_id={record.subdraft_id}; {type(exc).__name__}: {exc}"
            ) from exc
        _validate_generated_subdraft_record(record)
        subdraft_records.append(record)

    root_materials = cloned["materials"]
    parent_video = next(v for v in root_materials.get("videos", []) if v["id"] == parent_segment["material_id"])
    parent_video["duration"] = duration_us
    companion_keys = ("canvases", "material_animations", "placeholder_infos", "speeds", "sound_channel_mappings", "material_colors", "vocal_separations")
    parent_refs = set(parent_segment.get("extra_material_refs", []))
    companions = {key: [item for item in root_materials.get(key, []) if item.get("id") in parent_refs] for key in companion_keys}

    return {
        "overlay_id": str(overlay_row["overlay_id"]), "overlay_number": overlay_number, "overlay_class": "EVIDENCE",
        "start_us": start_us, "duration_us": duration_us, "parent_segment": parent_segment, "parent_video": parent_video,
        "outer_combo": outer_combo, "inner_combo": inner_combo, "outer_nested_draft_id": outer_draft["id"],
        "inner_parent_segment_id": inner_segment["id"], "text_nested_draft_id": text_draft["id"],
        "main_text_segment_id": "", "main_text_material_id": body_material["id"], "companions": companions,
        "subdrafts": subdraft_records, "expected_heading": heading,
        "expected_bullets": [str(overlay_row[f"bullet_{i}"]) for i in range(1, 4)],
        "heading_material_id": heading_material["id"], "body_material_id": body_material["id"],
        "entrance_keyframes": json.loads(json.dumps(inner_segment.get("common_keyframes", []))),
    }


def _evidence_visible_text(material: dict[str, Any]) -> str:
    try:
        return json.loads(material.get("content", ""))["text"]
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise CapCutExportError("Evidence rich-text material is malformed during structural validation") from exc


def _audit_evidence_compounds(draft: dict[str, Any], generated: list[dict[str, Any]], standard_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Evidence-specific structural validation after root assembly and physical writes."""
    uuid_re = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
    template_ids = set(uuid_re.findall(EVIDENCE_OVERLAY_REFERENCE_JSON.read_text(encoding="utf-8"))) if EVIDENCE_OVERLAY_REFERENCE_JSON.is_file() else set()
    generated_ids: set[str] = set()
    duplicate_ids = 0
    details = []
    evidence_track = next((t for t in draft.get("tracks", []) if t.get("name") == "Evidence Card Compounds"), None)
    if generated and evidence_track is None:
        raise CapCutExportError("Evidence track missing for generated Evidence overlays")

    def collect(obj: Any) -> None:
        nonlocal duplicate_ids
        if isinstance(obj, dict):
            value = obj.get("id")
            if isinstance(value, str) and uuid_re.fullmatch(value):
                key = value.lower()
                if key in generated_ids:
                    duplicate_ids += 1
                generated_ids.add(key)
            for v in obj.values(): collect(v)
        elif isinstance(obj, list):
            for v in obj: collect(v)

    # Root graph only; physical subdraft files intentionally mirror these IDs.
    for item in generated:
        collect(item["parent_segment"]); collect(item["parent_video"]); collect(item["outer_combo"]); collect(item["inner_combo"])
    reused = len({x.lower() for x in template_ids} & generated_ids)

    for item in generated:
        seg = item["parent_segment"]
        if seg not in evidence_track.get("segments", []):
            raise CapCutExportError(f"Evidence track entry missing for {item['overlay_id']}")
        if seg.get("target_timerange") != {"start": item["start_us"], "duration": item["duration_us"]}:
            raise CapCutExportError(f"Evidence canonical timing mismatch for {item['overlay_id']}")
        outer=item["outer_combo"]; inner=item["inner_combo"]
        outer_draft=outer["draft"]; inner_draft=inner["draft"]
        heading=next((m for m in outer_draft.get("materials",{}).get("texts",[]) if m.get("id")==item["heading_material_id"]),None)
        body=next((m for m in outer_draft.get("materials",{}).get("texts",[]) if m.get("id")==item["body_material_id"]),None)
        if heading is None or body is None:
            raise CapCutExportError(f"Evidence heading/body material missing for {item['overlay_id']}")
        if _evidence_visible_text(heading) != item["expected_heading"]:
            raise CapCutExportError(f"Evidence heading mismatch for {item['overlay_id']}")
        expected_body="\n".join(f"• {x}" for x in item["expected_bullets"])
        if _evidence_visible_text(body) != expected_body:
            raise CapCutExportError(f"Evidence bullet text mismatch for {item['overlay_id']}")
        separator=next((m for m in inner_draft.get("materials",{}).get("texts",[]) if m.get("font_path")=="C:/Windows/Fonts/impact.ttf"),None)
        if separator is None or _evidence_visible_text(separator) != "------------------------":
            raise CapCutExportError(f"Evidence separator missing for {item['overlay_id']}")
        if not any(c.get("type")=="canvas_color" and c.get("color")=="#ffffff" for c in outer_draft.get("materials",{}).get("canvases",[])):
            raise CapCutExportError(f"Evidence opaque white card canvas missing for {item['overlay_id']}")
        for record in item["subdrafts"]:
            _validate_generated_subdraft_record(record)
            raw=_read_text_long_safe(record.draft_content_path).replace("\\","/")
            if any(x in raw for x in EVIDENCE_DISALLOWED_SOURCE_PATHS):
                raise CapCutExportError(f"Machine-specific Evidence reference path survived in {record.draft_content_path}")
        outer_record=next(r for r in item["subdrafts"] if r.compound_level=="OUTER")
        outer_physical=json.loads(_read_text_long_safe(outer_record.draft_content_path))
        nested=outer_physical.get("materials",{}).get("drafts",[])
        if len(nested)!=1 or nested[0].get("id")!=inner.get("id") or not nested[0].get("draft_file_path"):
            raise CapCutExportError(f"Evidence OUTER physical subdraft does not resolve INNER for {item['overlay_id']}")
        details.append({"overlay_id":item["overlay_id"],"start_us":item["start_us"],"duration_us":item["duration_us"],"outer_subdraft":str(outer_record.physical_directory),"inner_subdraft":str(next(r.physical_directory for r in item["subdrafts"] if r.compound_level=="INNER")),"heading":item["expected_heading"],"bullets":item["expected_bullets"],"entrance_keyframes_preserved":bool(item["entrance_keyframes"])})

    if duplicate_ids or reused:
        raise CapCutExportError(f"Evidence UUID isolation failure: duplicate_ids={duplicate_ids}, reference_uuid_reuse={reused}")
    return {"generated_evidence_overlays":len(generated),"expected_physical_subdraft_folders":len(generated)*2,"physical_subdraft_folders":sum(len(x["subdrafts"]) for x in generated),"duplicate_id_occurrences":duplicate_ids,"reference_uuid_reuse_count":reused,"details":details}


def _audit_compound_overlays(draft: dict[str, Any], generated: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit generated compound relationships, physical payloads, UUID isolation and timing."""
    import re
    uuid_re = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
    material_drafts = {d["id"]: d for d in draft["materials"].get("drafts", [])}
    videos = {v["id"]: v for v in draft["materials"].get("videos", [])}
    root_material_ids = set()
    for values in draft.get("materials", {}).values():
        if isinstance(values, list):
            root_material_ids.update(x["id"] for x in values if isinstance(x, dict) and x.get("id"))

    reference_ids: set[str] = set()
    if TEXT_OVERLAY_REFERENCE_JSON.is_file():
        reference_ids = set(uuid_re.findall(TEXT_OVERLAY_REFERENCE_JSON.read_text(encoding="utf-8")))

    generated_json = json.dumps(draft, ensure_ascii=False)
    generated_uuid_tokens = set(uuid_re.findall(generated_json))
    reference_reuse = len({x.lower() for x in reference_ids} & {x.lower() for x in generated_uuid_tokens})

    dangling = 0
    details = []
    all_compound_ids: set[str] = set()
    duplicate_compound_ids = 0

    def collect_ids(obj: Any) -> None:
        nonlocal duplicate_compound_ids
        if isinstance(obj, dict):
            value = obj.get("id")
            if isinstance(value, str) and value:
                if value in all_compound_ids:
                    duplicate_compound_ids += 1
                all_compound_ids.add(value)
            for value in obj.values():
                collect_ids(value)
        elif isinstance(obj, list):
            for value in obj:
                collect_ids(value)

    for item in generated:
        # Count each overlay graph once, excluding its physical duplicate files.
        collect_ids({
            "parent_segment": item["parent_segment"],
            "parent_video": item["parent_video"],
            "outer_combo": item["outer_combo"],
            "inner_combo": item["inner_combo"],
            "companions": item["companions"],
        })

        seg = item["parent_segment"]
        outer = item["outer_combo"]
        inner = item["inner_combo"]
        outer_draft = outer["draft"]
        inner_seg = next(s for t in outer_draft["tracks"] if t["type"] == "video" for s in t["segments"])
        text_draft = inner["draft"]

        parent_ok = seg["material_id"] in videos
        parent_extra_ok = all(ref in root_material_ids for ref in seg.get("extra_material_refs", []))

        outer_material_ids = set()
        for values in outer_draft.get("materials", {}).values():
            if isinstance(values, list):
                outer_material_ids.update(x["id"] for x in values if isinstance(x, dict) and x.get("id"))
        # The inner combination is intentionally a root materials.drafts entry in
        # the proven CapCut 8.7 schema.
        inner_extra_ok = all(
            ref in outer_material_ids or ref in material_drafts
            for ref in inner_seg.get("extra_material_refs", [])
        )

        text_material_ids = {m["id"] for m in text_draft.get("materials", {}).get("texts", [])}
        text_refs_ok = all(
            s.get("material_id") in text_material_ids
            for t in text_draft.get("tracks", []) if t.get("type") == "text"
            for s in t.get("segments", [])
        )
        paths_ok = all(
            _path_is_file_long_safe(record.draft_content_path)
            and _path_is_file_long_safe(record.config_path)
            and _path_is_file_long_safe(record.cover_path)
            for record in item["subdrafts"]
        )
        by_level = {record.compound_level: record for record in item["subdrafts"]}
        outer_record = by_level["OUTER"]
        inner_record = by_level["INNER"]
        path_fields_ok = (
            outer["draft_file_path"] == outer_record.metadata_draft_path
            and outer["draft_config_path"] == outer_record.metadata_config_path
            and outer["draft_cover_path"] == outer_record.metadata_cover_path
            and inner["draft_file_path"] == inner_record.metadata_draft_path
            and inner["draft_config_path"] == inner_record.metadata_config_path
            and inner["draft_cover_path"] == inner_record.metadata_cover_path
        )

        failures = [
            not parent_ok, outer["id"] not in material_drafts, inner["id"] not in material_drafts,
            not parent_extra_ok, not inner_extra_ok, not text_refs_ok, not paths_ok, not path_fields_ok,
        ]
        dangling += sum(int(x) for x in failures)
        details.append({
            "overlay_id": item["overlay_id"],
            "start_us": item["start_us"],
            "end_us": item["start_us"] + item["duration_us"],
            "duration_us": item["duration_us"],
            "parent_segment_id": seg["id"],
            "parent_material_id": seg["material_id"],
            "outer_combination_material_id": outer["id"],
            "outer_combination_id": outer["combination_id"],
            "outer_nested_draft_id": item["outer_nested_draft_id"],
            "inner_parent_segment_id": item["inner_parent_segment_id"],
            "inner_combination_material_id": inner["id"],
            "inner_combination_id": inner["combination_id"],
            "text_nested_draft_id": item["text_nested_draft_id"],
            "main_text_segment_id": item["main_text_segment_id"],
            "main_text_material_id": item["main_text_material_id"],
            "physical_paths_resolve": paths_ok and path_fields_ok,
            "all_material_refs_resolve": parent_ok and parent_extra_ok and inner_extra_ok and text_refs_ok,
            "subdrafts": [
                {
                    "overlay_number": record.overlay_number,
                    "compound_level": record.compound_level,
                    "generated_subdraft_id": record.subdraft_id,
                    "referenced_path": record.metadata_draft_path,
                    "physical_directory": str(record.physical_directory),
                    "content_exists": _path_is_file_long_safe(record.draft_content_path),
                    "config_exists": _path_is_file_long_safe(record.config_path),
                    "cover_exists": _path_is_file_long_safe(record.cover_path),
                }
                for record in item["subdrafts"]
            ],
        })
    return {
        "generated_compound_overlays": len(generated),
        "expected_physical_subdraft_folders": len(generated) * 2,
        "physical_subdraft_folders": sum(len(x["subdrafts"]) for x in generated),
        "missing_physical_subdraft_folders": sum(
            1 for item in generated for record in item["subdrafts"]
            if not (
                _path_is_file_long_safe(record.draft_content_path)
                and _path_is_file_long_safe(record.config_path)
                and _path_is_file_long_safe(record.cover_path)
            )
        ),
        "total_unique_generated_uuid_count": len(all_compound_ids),
        "duplicate_id_occurrences": duplicate_compound_ids,
        "dangling_reference_count": dangling,
        "reference_uuid_reuse_count": reference_reuse,
        "details": details,
    }


@dataclass(frozen=True)
class ResolvedAsset:
    scene_id: str
    kind: str
    reference: str
    resolved_path: Path
    exists: bool
    placeholder: bool


def resolve_asset_reference(project_root: Path, reference: str) -> Path:
    """Resolve one manifest asset reference against the explicit project root.

    Relative references are always project-relative. Absolute references remain
    absolute. Backslashes in relative references are normalized so manifests
    remain portable between Windows and POSIX test environments.
    """
    project_root = Path(project_root).resolve()
    raw = str(reference).strip()
    if not raw:
        raise CapCutExportError("Asset reference is empty")

    native = Path(raw)
    windows_path = PureWindowsPath(raw)
    if native.is_absolute():
        return native.resolve()
    if windows_path.is_absolute():
        # On Windows, Path(raw) is a real absolute path. On non-Windows hosts,
        # retain the Windows absolute representation rather than prefixing the
        # project root.
        return Path(raw)

    normalized_parts = PureWindowsPath(raw.replace("/", "\\")).parts
    return project_root.joinpath(*normalized_parts).resolve()


def _avatar_references(scene: dict[str, Any]) -> list[str]:
    avatar = scene["assets"]["avatar"]
    references = avatar.get("references")
    if isinstance(references, list) and references:
        return [str(value) for value in references]
    reference = str(avatar.get("reference") or "").strip()
    if " to " in reference.lower():
        raise CapCutExportError(
            f"Scene {scene.get('scene_id', '<unknown>')} contains an unsplit avatar range reference: {reference}"
        )
    return [reference]


def validate_manifest_assets(
    scenes: list[dict[str, Any]],
    *,
    project_root: Path,
) -> list[ResolvedAsset]:
    """Resolve and validate every manifest asset from one explicit root."""
    resolved: list[ResolvedAsset] = []
    for scene in scenes:
        scene_id = str(scene["scene_id"])
        for reference in _avatar_references(scene):
            path = resolve_asset_reference(project_root, reference)
            resolved.append(ResolvedAsset(scene_id, "avatar", reference, path, path.is_file(), False))
        for kind in ("image", "broll"):
            asset = scene["assets"][kind]
            reference = str(asset["reference"])
            path = resolve_asset_reference(project_root, reference)
            resolved.append(ResolvedAsset(scene_id, kind, reference, path, path.is_file(), True))
    return resolved


def _asset_rows(resolved_assets: list[ResolvedAsset], *, project_root: Path) -> list[dict[str, Any]]:
    return [
        {
            "scene_id": asset.scene_id,
            "kind": asset.kind,
            "reference": asset.reference,
            "resolved_path": str(asset.resolved_path),
            "project_root": str(project_root),
            "exists": asset.exists,
            "placeholder": asset.placeholder,
        }
        for asset in resolved_assets
    ]


def _missing_asset_report_lines(resolved_assets: list[ResolvedAsset], *, project_root: Path) -> list[str]:
    missing = [asset for asset in resolved_assets if not asset.exists]
    if not missing:
        return ["- None"]
    lines: list[str] = []
    for asset in missing:
        lines.extend([
            f"### Scene {asset.scene_id} ({asset.kind})",
            f"- Reference: `{asset.reference}`",
            f"- Resolved path: `{asset.resolved_path}`",
            f"- Project root: `{project_root}`",
            "- Exists: No",
            "",
        ])
    return lines



def _write_json(path: Path, payload: Any) -> None:
    """Write JSON using extended-length Win32 I/O when the bundle path is long."""
    path.parent.mkdir(parents=True, exist_ok=True)
    io_path = _windows_long_io_path(path)
    with open(io_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _mkdir_long_safe(path: Path) -> None:
    os.makedirs(_windows_long_io_path(path), exist_ok=True)


def _read_bytes_long_safe(path: Path) -> bytes:
    with open(_windows_long_io_path(path), "rb") as handle:
        return handle.read()


def _read_text_long_safe(path: Path, *, encoding: str = "utf-8") -> str:
    with open(_windows_long_io_path(path), "r", encoding=encoding) as handle:
        return handle.read()


def _path_is_dir_long_safe(path: Path) -> bool:
    try:
        return os.path.isdir(_windows_long_io_path(path))
    except OSError:
        return False


def _physical_file_record(path: Path, *, referenced_by: str) -> dict[str, Any]:
    exists = _path_is_file_long_safe(path)
    size = 0
    sha256 = ""
    if exists:
        data = _read_bytes_long_safe(path)
        size = len(data)
        sha256 = hashlib.sha256(data).hexdigest()
    return {
        "path": str(path),
        "referenced_by": referenced_by,
        "exists": exists,
        "size": size,
        "sha256": sha256,
    }


def _audit_capcut_physical_files(
    *,
    draft_dir: Path,
    timeline_id: str,
    generated_compounds: list[dict[str, Any]],
) -> dict[str, Any]:
    """Audit every physical file referenced by the final CapCut 8.7 bundle."""
    records: list[dict[str, Any]] = [
        _physical_file_record(
            draft_dir / "draft_content.json",
            referenced_by="CapCut_Project root draft",
        ),
        _physical_file_record(
            draft_dir / "Timelines" / timeline_id / "draft_content.json",
            referenced_by=f"timeline_id={timeline_id}",
        ),
    ]
    for compound in generated_compounds:
        for subdraft in compound["subdrafts"]:
            prefix = (
                f"overlay_number={subdraft.overlay_number};"
                f"overlay_id={subdraft.overlay_id};"
                f"compound_level={subdraft.compound_level};"
                f"subdraft_id={subdraft.subdraft_id}"
            )
            records.extend([
                _physical_file_record(subdraft.draft_content_path, referenced_by=prefix + ";draft_file_path"),
                _physical_file_record(subdraft.config_path, referenced_by=prefix + ";draft_config_path"),
                _physical_file_record(subdraft.cover_path, referenced_by=prefix + ";draft_cover_path"),
            ])
    missing = [record for record in records if not record["exists"]]
    if missing:
        first = missing[0]
        raise CapCutExportError(
            "CapCut physical-file integrity failure: "
            f"path={first['path']}; referenced_by={first['referenced_by']}"
        )
    return {
        "timeline_id": timeline_id,
        "referenced_file_count": len(records),
        "missing_referenced_physical_paths": 0,
        "files": records,
    }


def _create_capcut_87_bundle(
    draft_dir: Path,
    *,
    draft: dict[str, Any],
    meta: dict[str, Any],
    draft_id: str,
    timeline_id: str,
    project_name: str,
) -> list[str]:
    """Write the observed CapCut Desktop 8.7 Windows multi-file draft layout.

    All readable timeline mirrors receive the same payload so CapCut 8.7 cannot
    prefer a stale secondary target over the root timeline.
    """
    for dirname in CAPCUT_87_AUXILIARY_DIRS:
        _mkdir_long_safe(draft_dir / dirname)

    timeline_dir = draft_dir / "Timelines" / timeline_id
    _mkdir_long_safe(timeline_dir)

    root_content = draft_dir / "draft_content.json"
    timeline_content = timeline_dir / "draft_content.json"
    template_mirror = draft_dir / "template-2.tmp"
    _write_json(root_content, draft)
    _write_json(timeline_content, draft)
    _write_json(template_mirror, draft)

    meta = dict(meta)
    meta.update({
        "draft_id": draft_id,
        "draft_name": project_name,
        "timeline_id": timeline_id,
        "timeline_path": f"Timelines/{timeline_id}/draft_content.json",
        "timeline_count": 1,
        "schema_version": CAPCUT_SCHEMA_VERSION,
    })
    _write_json(draft_dir / "draft_meta_info.json", meta)

    defaults: dict[str, Any] = {
        "draft_agency_config.json": {},
        "draft_biz_config.json": {},
        "attachment_pc_common.json": {"attachments": []},
        "performance_opt_info.json": {"version": 1, "items": []},
    }
    for filename, payload in defaults.items():
        _write_json(draft_dir / filename, payload)

    layout = {
        "version": 1,
        "draft_id": draft_id,
        "active_timeline_id": timeline_id,
        "timelines": [{
            "id": timeline_id,
            "name": project_name,
            "path": f"Timelines/{timeline_id}/draft_content.json",
            "duration": draft["duration"],
        }],
    }
    _write_json(draft_dir / "timeline_layout.json", layout)
    _write_json(draft_dir / "draft_settings", {
        "version": 1,
        "draft_id": draft_id,
        "active_timeline_id": timeline_id,
    })

    created = [
        "draft_content.json", "draft_meta_info.json", "template-2.tmp",
        "timeline_layout.json", "draft_settings",
        *CAPCUT_87_ROOT_JSON_FILES,
        f"Timelines/{timeline_id}/draft_content.json",
    ]
    created.extend(f"{name}/" for name in CAPCUT_87_AUXILIARY_DIRS)
    return created


def validate_capcut_87_bundle(draft_dir: Path) -> list[str]:
    required_files = [
        "draft_content.json", "draft_meta_info.json", "draft_agency_config.json",
        "draft_biz_config.json", "attachment_pc_common.json",
        "performance_opt_info.json", "timeline_layout.json", "draft_settings",
        "template-2.tmp",
    ]
    missing = [name for name in required_files if not _path_is_file_long_safe(draft_dir / name)]
    missing.extend(
        name + "/" for name in CAPCUT_87_AUXILIARY_DIRS
        if not _path_is_dir_long_safe(draft_dir / name)
    )
    if missing:
        raise CapCutExportError("Incomplete CapCut 8.7 draft bundle; missing: " + ", ".join(missing))

    layout = json.loads(_read_text_long_safe(draft_dir / "timeline_layout.json"))
    meta = json.loads(_read_text_long_safe(draft_dir / "draft_meta_info.json"))
    settings = json.loads(_read_text_long_safe(draft_dir / "draft_settings"))
    root_draft = json.loads(_read_text_long_safe(draft_dir / "draft_content.json"))

    timeline = layout["timelines"][0]
    timeline_id = str(timeline["id"])
    expected_rel = f"Timelines/{timeline_id}/draft_content.json"
    if timeline["path"] != expected_rel:
        raise CapCutExportError(
            f"CapCut timeline path/ID mismatch: id={timeline_id}, path={timeline['path']}"
        )
    if layout.get("active_timeline_id") != timeline_id:
        raise CapCutExportError("timeline_layout active_timeline_id does not match timeline directory ID")
    if meta.get("timeline_id") != timeline_id or meta.get("timeline_path") != expected_rel:
        raise CapCutExportError("draft_meta_info timeline ID/path does not match timeline directory ID")
    if settings.get("active_timeline_id") != timeline_id:
        raise CapCutExportError("draft_settings active_timeline_id does not match timeline directory ID")
    if root_draft.get("timeline_id") != timeline_id:
        raise CapCutExportError("root draft timeline_id does not match timeline directory ID")

    timeline_path = draft_dir / "Timelines" / timeline_id / "draft_content.json"
    if not _path_is_file_long_safe(timeline_path):
        raise CapCutExportError(f"CapCut 8.7 timeline mirror is missing: {timeline_path}")

    root_bytes = _read_bytes_long_safe(draft_dir / "draft_content.json")
    for mirror in (timeline_path, draft_dir / "template-2.tmp"):
        if _read_bytes_long_safe(mirror) != root_bytes:
            raise CapCutExportError(f"CapCut 8.7 timeline mirror is out of sync: {mirror}")
    return required_files + [expected_rel]


def _make_placeholder_png(path: Path, *, title: str, scene_id: str, start: float, end: float) -> None:
    """Create a deterministic visible 1920x1080 planning placeholder."""
    from PIL import Image, ImageDraw, ImageFont

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1920, 1080), (24, 31, 48))
    draw = ImageDraw.Draw(image)
    try:
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 112)
        medium = ImageFont.truetype("DejaVuSans-Bold.ttf", 58)
        small = ImageFont.truetype("DejaVuSans.ttf", 44)
    except OSError:
        big = medium = small = ImageFont.load_default()
    lines = [title, f"Scene: {scene_id}", f"{start:.3f}s - {end:.3f}s"]
    fonts = [big, medium, small]
    y = 340
    for text, font in zip(lines, fonts):
        box = draw.textbbox((0, 0), text, font=font)
        width = box[2] - box[0]
        draw.text(((1920 - width) / 2, y), text, fill=(245, 245, 245), font=font)
        y += 155
    image.save(path, format="PNG", optimize=False, compress_level=9)


def _base_avatar_assets(manifest: dict[str, Any], project_root: Path) -> tuple[list[dict[str, Any]], list[ResolvedAsset]]:
    base = manifest.get("base_avatar")
    if not isinstance(base, dict) or not isinstance(base.get("chunks"), list) or not base["chunks"]:
        raise CapCutExportError(
            "timeline_manifest.json is missing authoritative base_avatar chunk timing from avatar_timing_manifest.json"
        )
    chunks = base["chunks"]
    resolved: list[ResolvedAsset] = []
    previous_end_us: int | None = None
    normalized: list[dict[str, Any]] = []
    for chunk in chunks:
        name = str(chunk.get("filename") or Path(str(chunk.get("reference") or "")).name)
        ref = str(chunk.get("reference") or "").strip()
        if not ref:
            raise CapCutExportError(f"Avatar chunk {name or '<unknown>'} is missing a manifest reference")
        start_us = _us(chunk["start_seconds"])
        end_us = _us(chunk["end_seconds"])
        duration_us = _us(chunk["duration_seconds"])
        if end_us - start_us != duration_us or duration_us <= 0:
            raise CapCutExportError(f"Avatar chunk {name} has inconsistent authoritative timing")
        if previous_end_us is not None and start_us != previous_end_us:
            raise CapCutExportError(
                f"Avatar chunks are not continuous at {name}: previous end {previous_end_us}, start {start_us}"
            )
        previous_end_us = end_us
        path = resolve_asset_reference(project_root, ref)
        resolved.append(ResolvedAsset(f"BASE:{name}", "avatar", ref, path, path.is_file(), False))
        normalized.append({**chunk, "filename": name, "reference": ref, "path": path,
                           "start_us": start_us, "end_us": end_us, "duration_us": duration_us})
    total_us = _us(base["total_duration_seconds"])
    if normalized[-1]["end_us"] != total_us:
        raise CapCutExportError(
            f"Final base-track duration {normalized[-1]['end_us']} does not equal avatar manifest total {total_us}"
        )
    return normalized, resolved


def _visual_assets(manifest: dict[str, Any], project_root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    image_no = 0
    broll_no = 0
    for scene in manifest["scenes"]:
        assignment = scene.get("visual_assignment")
        if not isinstance(assignment, dict):
            continue
        kind = assignment.get("kind")
        if kind not in {"image", "broll"}:
            continue
        if kind == "image":
            image_no += 1
            slot_no = image_no
            placeholder_ref = f"assets/placeholders/images/image_{slot_no:03d}.png"
            title = f"AI IMAGE {slot_no:03d}"
        else:
            broll_no += 1
            slot_no = broll_no
            # A PNG is intentionally used as the lightweight CapCut-compatible visual
            # planning representation for missing video B-roll.
            placeholder_ref = f"assets/placeholders/broll/broll_{slot_no:03d}.png"
            title = f"B-ROLL {slot_no:03d}"
        real_ref = str(assignment.get("reference") or "").strip()
        if not real_ref:
            raise CapCutExportError(f"Scene {scene['scene_id']} {kind} assignment is missing an asset reference")
        real_path = resolve_asset_reference(project_root, real_ref)
        placeholder_path = resolve_asset_reference(project_root, placeholder_ref)
        timing = scene["timing"]
        if real_path.is_file():
            chosen_path = real_path
            using_placeholder = False
        else:
            _make_placeholder_png(
                placeholder_path, title=title, scene_id=scene["scene_id"],
                start=float(timing["start_seconds"]), end=float(timing["end_seconds"]),
            )
            chosen_path = placeholder_path
            using_placeholder = True
        items.append({
            "scene_id": scene["scene_id"], "kind": kind, "slot_id": assignment.get("slot_id"),
            "prompt_id": assignment.get("prompt_id", ""), "reference": real_ref,
            "real_path": real_path, "real_exists": real_path.is_file(),
            "placeholder_reference": placeholder_ref, "placeholder_path": placeholder_path,
            "chosen_path": chosen_path, "using_placeholder": using_placeholder,
            "start_us": _us(timing["start_seconds"]), "duration_us": _us(timing["duration_seconds"]),
            "start_seconds": float(timing["start_seconds"]), "end_seconds": float(timing["end_seconds"]),
        })
    return items


def _validate_avatar_sync(video_segments: list[dict[str, Any]], audio_segments: list[dict[str, Any]], chunks: list[dict[str, Any]], total_us: int) -> tuple[list[dict[str, Any]], int]:
    if len(video_segments) != len(chunks) or len(audio_segments) != len(chunks):
        raise CapCutExportError("Avatar sync validation failed: each chunk must appear exactly once on V1 and A1")
    diagnostics: list[dict[str, Any]] = []
    maximum_difference = 0
    for chunk, video, audio in zip(chunks, video_segments, audio_segments):
        vt = video["target_timerange"]; at = audio["target_timerange"]
        vs = video["source_timerange"]; ass = audio["source_timerange"]
        if vt != at or vs != ass:
            raise CapCutExportError(f"Avatar sync validation failed for {chunk['filename']}: V1/A1 ranges differ")
        if vt["start"] != chunk["start_us"] or vt["duration"] != chunk["duration_us"]:
            raise CapCutExportError(f"Avatar sync validation failed for {chunk['filename']}: target range differs from avatar manifest")
        if vs != {"start": 0, "duration": chunk["duration_us"]}:
            raise CapCutExportError(f"Avatar sync validation failed for {chunk['filename']}: source range must use the complete chunk")
        video_end = vt["start"] + vt["duration"]
        audio_end = at["start"] + at["duration"]
        difference = max(abs(vt["start"] - at["start"]), abs(video_end - audio_end))
        maximum_difference = max(maximum_difference, difference)
        diagnostics.append({
            "chunk": chunk["filename"], "video_start_us": vt["start"], "video_end_us": video_end,
            "audio_start_us": at["start"], "audio_end_us": audio_end, "difference_us": difference,
        })
    for previous, current in zip(video_segments, video_segments[1:]):
        previous_end = previous["target_timerange"]["start"] + previous["target_timerange"]["duration"]
        if current["target_timerange"]["start"] != previous_end:
            raise CapCutExportError("Avatar sync validation failed: base avatar chunks contain a gap or overlap")
    last_end = video_segments[-1]["target_timerange"]["start"] + video_segments[-1]["target_timerange"]["duration"]
    if last_end != total_us:
        raise CapCutExportError("Avatar sync validation failed: final V1 duration differs from avatar timing manifest")
    return diagnostics, maximum_difference


def export_capcut_project(project_root: Path, manifest_path: Path | None = None) -> CapCutExportResult:
    project_root = Path(project_root).resolve()
    manifest_path = Path(manifest_path or project_root / "capcut" / "timeline_manifest.json")
    manifest = load_timeline_manifest(manifest_path)
    scenes = manifest["scenes"]
    if not scenes:
        raise CapCutExportError("Timeline manifest contains no scenes")

    capcut_root = project_root / "capcut"
    capcut_root.mkdir(parents=True, exist_ok=True)
    draft_dir = capcut_root / "CapCut_Project"
    # CapCut/Explorer can remove a draft file between exists() and rmtree() on
    # Windows.  Treat ENOENT as the desired end state, but do not suppress
    # permission/locking errors or any other filesystem failure.
    if draft_dir.exists():
        try:
            shutil.rmtree(draft_dir)
        except FileNotFoundError:
            pass
    draft_dir.mkdir(parents=True, exist_ok=True)

    chunks, avatar_assets = _base_avatar_assets(manifest, project_root)
    required_missing = [asset for asset in avatar_assets if not asset.exists]
    visuals = _visual_assets(manifest, project_root)
    warnings: list[str] = []
    placeholder_images = [item for item in visuals if item["kind"] == "image" and item["using_placeholder"]]
    placeholder_broll = [item for item in visuals if item["kind"] == "broll" and item["using_placeholder"]]
    if placeholder_images:
        warnings.append(f"AI image placeholders awaiting replacement: {len(placeholder_images)}")
    if placeholder_broll:
        warnings.append(f"B-roll placeholders awaiting replacement: {len(placeholder_broll)}")

    materials_videos: list[dict[str, Any]] = []
    materials_audios: list[dict[str, Any]] = []
    materials_texts: list[dict[str, Any]] = []
    materials_drafts: list[dict[str, Any]] = []
    compound_companions: dict[str, list[dict[str, Any]]] = {
        key: [] for key in ("canvases", "material_animations", "placeholder_infos", "speeds",
                            "sound_channel_mappings", "material_colors", "vocal_separations")
    }
    generated_compounds: list[dict[str, Any]] = []
    generated_evidence_compounds: list[dict[str, Any]] = []
    evidence_template_load_count = 0
    tracks = {name: [] for name in ("V1", "V2", "V3", "A1", "T1", "T2")}
    image_motion_diagnostics: list[dict[str, Any]] = []

    # Authoritative base narration: one complete V1/A1 pair per avatar chunk.
    for chunk in chunks:
        avatar_mid = _id(f"avatar-material:{chunk['reference']}")
        audio_mid = _id(f"audio-material:{chunk['reference']}")
        materials_videos.append(_video_material(
            avatar_mid, chunk["path"], photo=False, name=chunk["filename"], duration_us=chunk["duration_us"]
        ))
        materials_audios.append({
            "id": audio_mid, "name": chunk["filename"], "path": str(chunk["path"]),
            "duration": chunk["duration_us"], "type": "extract_music",
        })
        tracks["V1"].append(_segment(
            _id(f"V1:chunk:{chunk['filename']}"), avatar_mid, chunk["start_us"], chunk["duration_us"],
            source_start_us=0, muted=True,
        ))
        tracks["A1"].append(_segment(
            _id(f"A1:chunk:{chunk['filename']}"), audio_mid, chunk["start_us"], chunk["duration_us"],
            source_start_us=0,
        ))

    # Production visuals use scene timing only; they never alter the base avatar track.
    image_assignment_index = 0
    for item in visuals:
        material_id = _id(f"{item['kind']}-material:{item['scene_id']}:{item['slot_id']}")
        # AI images and STOCK_IMAGE B-roll are still photos.  The timeline keeps both
        # stock video and stock stills in the V3 B-roll lane, but CapCut must receive
        # photo=True for still media or it may import/render it incorrectly.
        is_photo = (
            item["kind"] == "image"
            or item["using_placeholder"]
            or item["chosen_path"].suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        )
        materials_videos.append(_video_material(
            material_id, item["chosen_path"], photo=is_photo, name=item["chosen_path"].name,
            duration_us=item["duration_us"],
        ))
        track = "V2" if item["kind"] == "image" else "V3"
        segment = _segment(
            _id(f"{track}:{item['scene_id']}:{item['slot_id']}"), material_id,
            item["start_us"], item["duration_us"], source_start_us=0, muted=True,
        )
        if item["kind"] == "image":
            image_assignment_index += 1
            _apply_image_zoom(segment, image_assignment_index=image_assignment_index)
            zoom_in = image_assignment_index % 2 == 1
            frames = segment["common_keyframes"][0]["keyframe_list"]
            image_motion_diagnostics.append({
                "image": item["chosen_path"].name,
                "motion": "ZOOM_IN" if zoom_in else "ZOOM_OUT",
                "start_scale": frames[0]["values"][0],
                "end_scale": frames[1]["values"][0],
                "duration_us": item["duration_us"],
                "keyframe_count": len(frames),
            })
        tracks[track].append(segment)

    # Optional validated Text Overlay artifact. Every READY/WARNING row becomes
    # one LIVE-VERIFIED two-level CapCut 8.7 compound VIDEO overlay. Timing is
    # consumed exactly from 11_text_overlays.csv and is never recalculated here.
    overlay_path = project_root / ARTIFACT_NAME
    overlay_rows = load_artifact(overlay_path) if overlay_path.is_file() else []
    _assert_resolved_overlay_schedule(overlay_rows)
    ready_overlay_rows = [
        row for row in overlay_rows
        if str(row.get("status", "")).upper() in {"READY", "WARNING"}
        and str(row.get("overlay_class", "STANDARD")).upper() == "STANDARD"
    ]
    ready_evidence_rows = [
        row for row in overlay_rows
        if str(row.get("status", "")).upper() in {"READY", "WARNING"}
        and str(row.get("overlay_class", "STANDARD")).upper() == "EVIDENCE"
    ]
    draft_path_placeholder = f"##_draftpath_placeholder_{_fresh_uuid()}_##"
    for row in ready_overlay_rows:
        compound = _build_compound_overlay(
            overlay_row=row,
            draft_dir=draft_dir,
            draft_path_placeholder=draft_path_placeholder,
        )
        generated_compounds.append(compound)
        materials_videos.append(compound["parent_video"])
        materials_drafts.extend([compound["outer_combo"], compound["inner_combo"]])
        for key, values in compound["companions"].items():
            compound_companions[key].extend(values)
        tracks["T1"].append(compound["parent_segment"])

    # Evidence master is intentionally lazy: zero Evidence rows means zero template reads and no T2.
    if ready_evidence_rows:
        evidence_master, evidence_config_template = _load_evidence_overlay_master()
        evidence_template_load_count = 1
        for row in ready_evidence_rows:
            compound = _build_evidence_compound(
                overlay_row=row, evidence_master=evidence_master, config_template=evidence_config_template,
                draft_dir=draft_dir, draft_path_placeholder=draft_path_placeholder,
            )
            generated_evidence_compounds.append(compound)
            materials_videos.append(compound["parent_video"])
            materials_drafts.extend([compound["outer_combo"], compound["inner_combo"]])
            for key, values in compound["companions"].items():
                compound_companions[key].extend(values)
            tracks["T2"].append(compound["parent_segment"])

    total_us = _us(manifest["base_avatar"]["total_duration_seconds"])
    sync_diagnostics, max_sync_difference_us = _validate_avatar_sync(
        tracks["V1"], tracks["A1"], chunks, total_us
    )

    draft_id = _id(f"draft:{project_root.name}")
    timeline_id = _id(f"timeline:{project_root.name}:main")
    track_defs = [
        {"id": _id("track:V1"), "type": "video", "name": "V1 Avatar", "segments": tracks["V1"], "flag": 0},
        {"id": _id("track:V2"), "type": "video", "name": "V2 Images", "segments": tracks["V2"], "flag": 0},
        {"id": _id("track:V3"), "type": "video", "name": "V3 B-roll", "segments": tracks["V3"], "flag": 0},
        {"id": _id("track:A1"), "type": "audio", "name": "A1 Avatar Audio", "segments": tracks["A1"], "flag": 0},
        {"id": _id("track:T1"), "type": "video", "name": "Text Overlay Compounds", "segments": tracks["T1"], "flag": 0},
    ]
    if ready_evidence_rows:
        track_defs.append({"id": _id("track:T2"), "type": "video", "name": "Evidence Card Compounds", "segments": tracks["T2"], "flag": 0})
    draft = {
        "id": draft_id, "timeline_id": timeline_id, "name": project_root.name, "duration": total_us, "fps": 30,
        "version": CAPCUT_SCHEMA_VERSION,
        "canvas_config": {"width": 1920, "height": 1080, "ratio": "16:9"},
        "platform": {"app_source": "cc", "app_version": CAPCUT_APP_VERSION, "os": "windows"},
        "last_modified_platform": {"app_source": "cc", "app_version": CAPCUT_APP_VERSION, "os": "windows"},
        "new_version": CAPCUT_NATIVE_NEW_VERSION, "free_render_index_mode_on": False,
        "tracks": track_defs,
        "materials": {"videos": materials_videos, "audios": materials_audios, "texts": materials_texts,
                      "drafts": materials_drafts, "stickers": [], "video_effects": [],
                      "material_animations": compound_companions["material_animations"], "transitions": [],
                      "masks": [], "common_masks": [], "canvases": compound_companions["canvases"],
                      "speeds": compound_companions["speeds"], "audio_fades": [],
                      "placeholder_infos": compound_companions["placeholder_infos"],
                      "vocal_separations": compound_companions["vocal_separations"],
                      "sound_channel_mappings": compound_companions["sound_channel_mappings"],
                      "material_colors": compound_companions["material_colors"],
                      "smart_crops": [], "manual_deformations": []},
        "extra_info": {"generator": "Senior Health AI V3.4", "timeline_manifest": "../timeline_manifest.json",
                       "supported_schema": SUPPORTED_CAPCUT_SCHEMA},
    }
    compound_audit = _audit_compound_overlays(draft, generated_compounds)
    _write_json(capcut_root / "text_overlay_compound_audit.json", compound_audit)
    evidence_audit = _audit_evidence_compounds(draft, generated_evidence_compounds, ready_overlay_rows)
    _write_json(capcut_root / "evidence_overlay_compound_audit.json", evidence_audit)
    if (compound_audit["dangling_reference_count"] or compound_audit["duplicate_id_occurrences"]
            or compound_audit["reference_uuid_reuse_count"]
            or compound_audit["missing_physical_subdraft_folders"]):
        raise CapCutExportError(
            "Text Overlay compound integrity failure: "
            f"dangling={compound_audit['dangling_reference_count']}, "
            f"duplicate_ids={compound_audit['duplicate_id_occurrences']}, "
            f"reference_uuid_reuse={compound_audit['reference_uuid_reuse_count']}, "
            f"missing_physical_subdrafts={compound_audit['missing_physical_subdraft_folders']}"
        )

    meta = {"draft_id": draft_id, "draft_name": project_root.name, "draft_fold_path": str(draft_dir),
            "draft_root_path": str(draft_dir), "draft_timeline_materials_size_": 0,
            "tm_draft_create": 0, "tm_draft_modified": 0, "draft_duration": total_us,
            "draft_removable_storage_device": "", "draft_cloud_last_action_download": False,
            "draft_is_ai_shorts": False, "draft_type": "video", "version": CAPCUT_APP_VERSION}

    # Write asset/report data before raising missing-avatar errors so diagnostics persist.
    asset_rows = [
        {"scene_id": asset.scene_id, "kind": "avatar", "reference": asset.reference,
         "resolved_path": str(asset.resolved_path), "project_root": str(project_root),
         "exists": asset.exists, "required": True, "placeholder": False}
        for asset in avatar_assets
    ]
    asset_rows.extend({
        "scene_id": item["scene_id"], "kind": item["kind"], "reference": item["reference"],
        "resolved_path": str(item["real_path"]), "project_root": str(project_root),
        "exists": item["real_exists"], "required": False, "placeholder": item["using_placeholder"],
        "placeholder_path": str(item["placeholder_path"]) if item["using_placeholder"] else "",
        "slot_id": item["slot_id"], "prompt_id": item["prompt_id"],
    } for item in visuals)

    if not required_missing:
        created_project_entries = _create_capcut_87_bundle(
            draft_dir, draft=draft, meta=meta, draft_id=draft_id, timeline_id=timeline_id,
            project_name=project_root.name,
        )
        # Physical integrity is checked only AFTER root/timeline/config writes are complete.
        physical_file_audit = _audit_capcut_physical_files(
            draft_dir=draft_dir,
            timeline_id=timeline_id,
            generated_compounds=generated_compounds + generated_evidence_compounds,
        )
        _write_json(capcut_root / "physical_file_audit.json", physical_file_audit)
        validated_project_files = validate_capcut_87_bundle(draft_dir)
    else:
        physical_file_audit = {
            "timeline_id": timeline_id,
            "referenced_file_count": 0,
            "missing_referenced_physical_paths": 0,
            "files": [],
        }
        created_project_entries = []
        validated_project_files = []

    asset_manifest = {
        "schema_version": "1.1", "assets": asset_rows,
        "required_avatar_missing_count": len(required_missing),
        "image_assignment_count": sum(item["kind"] == "image" for item in visuals),
        "broll_assignment_count": sum(item["kind"] == "broll" for item in visuals),
        "image_placeholders_remaining": len(placeholder_images),
        "broll_placeholders_remaining": len(placeholder_broll),
        "final_assets_ready": not placeholder_images and not placeholder_broll and not required_missing,
    }
    _write_json(capcut_root / "asset_manifest.json", asset_manifest)

    status = "FAIL" if required_missing else ("PROJECT GENERATED / PREVIEW READY" if warnings else "FINAL ASSETS READY")
    report = [
        "# CapCut Export Report", "", f"- Status: **{status}**", f"- Supported format: {SUPPORTED_CAPCUT_SCHEMA}",
        f"- CapCut app version marker: {CAPCUT_APP_VERSION}",
        f"- Project entries created: {len(created_project_entries)}",
        f"- Timeline ID: {timeline_id}",
        f"- Physical referenced files audited: {physical_file_audit['referenced_file_count']}",
        f"- Missing referenced physical paths: {physical_file_audit['missing_referenced_physical_paths']}",
        f"- Structure validation: {'PASS' if not required_missing else 'NOT WRITTEN'} ({len(validated_project_files)} files verified)",
        f"- Production scenes: {len(scenes)}", f"- Avatar chunks on V1: {len(tracks['V1'])}",
        f"- Avatar chunks on A1: {len(tracks['A1'])}", f"- Final V1/A1 duration: {total_us / 1_000_000:.6f} seconds",
        f"- Maximum V1/A1 sync difference: {max_sync_difference_us} microseconds",
        f"- AI image slots: {len(tracks['V2'])}", f"- B-roll slots: {len(tracks['V3'])}",
        f"- READY text overlays: {len(ready_overlay_rows)}",
        f"- READY evidence overlays: {len(ready_evidence_rows)}",
        f"- Evidence template loads this export: {evidence_template_load_count}",
        f"- Generated compound overlays: {compound_audit['generated_compound_overlays']}",
        f"- Generated evidence compounds: {evidence_audit['generated_evidence_overlays']}",
        f"- Generated physical evidence subdraft folders: {evidence_audit['physical_subdraft_folders']}",
        f"- Evidence reference UUID reuse: {evidence_audit['reference_uuid_reuse_count']}",
        f"- Expected physical text-overlay subdraft folders: {compound_audit['expected_physical_subdraft_folders']}",
        f"- Generated physical text-overlay subdraft folders: {compound_audit['physical_subdraft_folders']}",
        f"- Missing physical text-overlay subdraft folders: {compound_audit['missing_physical_subdraft_folders']}",
        f"- Text-overlay dangling references: {compound_audit['dangling_reference_count']}",
        f"- Text-overlay reference UUID reuse: {compound_audit['reference_uuid_reuse_count']}",
        f"- Text overlay artifact: {overlay_path.name if overlay_rows else 'none'}",
        f"- AI image motion: native common_keyframes / KFTypeScaleX + uniform_scale lock, alternating Zoom In/Out",
        f"- AI image zoom range: 1.00 ↔ {AI_IMAGE_ZOOM_SCALE:.2f}",
        f"- AI image segments receiving motion: {len(tracks['V2'])}",
        f"- AI image placeholders awaiting real assets: {len(placeholder_images)}",
        f"- B-roll placeholders awaiting real assets: {len(placeholder_broll)}",
        f"- Required avatar assets missing: {len(required_missing)}", "", "## Avatar Sync Diagnostics", "",
        "| Chunk | Video Start | Video End | Audio Start | Audio End | Difference |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in sync_diagnostics:
        report.append(
            f"| {row['chunk']} | {row['video_start_us']/1e6:.6f} | {row['video_end_us']/1e6:.6f} | "
            f"{row['audio_start_us']/1e6:.6f} | {row['audio_end_us']/1e6:.6f} | {row['difference_us']} us |"
        )
    report.extend(["", "## Missing Required Avatar Assets", ""])
    if required_missing:
        for asset in required_missing:
            report.extend([
                f"### {asset.scene_id}", f"- Reference: `{asset.reference}`",
                f"- Resolved path: `{asset.resolved_path}`", f"- Project root: `{project_root}`", "- Exists: No", "",
            ])
    else:
        report.append("- None")
    report.extend(["", "## AI Image Motion Diagnostics", ""])
    if image_motion_diagnostics:
        for row in image_motion_diagnostics:
            report.extend([
                f"### {row['image']}",
                f"- Motion: {row['motion']}",
                f"- Start scale: {row['start_scale']:.2f}",
                f"- End scale: {row['end_scale']:.2f}",
                f"- Segment duration: {row['duration_us'] / 1_000_000:.6f} seconds ({row['duration_us']} us)",
                f"- CapCut keyframe count: {row['keyframe_count']}",
                "",
            ])
    else:
        report.append("- None")
    report.extend(["", "## Production Placeholders Requiring Replacement", ""])
    remaining = placeholder_images + placeholder_broll
    if remaining:
        for item in remaining:
            report.append(
                f"- {item['slot_id']} · Scene {item['scene_id']} · real asset `{item['reference']}` · "
                f"preview placeholder `{item['placeholder_reference']}`"
            )
    else:
        report.append("- None")
    if warnings:
        report.extend(["", "## Warnings", *[f"- {warning}" for warning in warnings]])
    (capcut_root / "export_report.md").write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")

    if required_missing:
        raise CapCutExportError("Missing required avatar assets; export report was generated with FAIL status")
    return CapCutExportResult(True, draft_dir, len(scenes), total_us / 1_000_000, [], warnings)
