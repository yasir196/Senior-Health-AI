import capcut_export
import shutil
import csv
import json
from pathlib import Path

import pytest

from capcut_export import CapCutExportError, export_capcut_project, resolve_asset_reference
from timeline_builder import build_timeline_manifest
from test_timeline_builder import make_project


def write_avatar_manifest(project: Path, durations: list[float]) -> None:
    chunks = []
    start = 0.0
    for i, duration in enumerate(durations, start=1):
        end = start + duration
        chunks.append({
            "chunk_filename": f"c{i}.mp4",
            "duration": duration,
            "global_audio_start": start,
            "global_audio_end": end,
        })
        start = end
    (project / "avatar_timing_manifest.json").write_text(json.dumps({
        "timeline_status": "PASS",
        "total_avatar_duration": start,
        "chunks": chunks,
    }), encoding="utf-8")


def write_production_sheet(project: Path, assignments: dict[str, str]) -> None:
    fields = ["scene_id", "recommended_asset_type", "image_prompt_id", "broll_prompt_id", "selected_asset_path"]
    with (project / "07_production_sheet.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        image_no = 0
        broll_no = 0
        for scene_id, kind in assignments.items():
            row = {"scene_id": scene_id, "recommended_asset_type": kind}
            if kind == "AI_IMAGE":
                image_no += 1
                row["image_prompt_id"] = f"IMG-{image_no:03d}"
            elif kind == "STOCK_VIDEO":
                broll_no += 1
                row["broll_prompt_id"] = f"BR-{broll_no:03d}"
            writer.writerow(row)


def create_avatar_files(project: Path, count: int) -> None:
    folder = project / "avatars"
    folder.mkdir(exist_ok=True)
    for i in range(1, count + 1):
        (folder / f"c{i}.mp4").write_bytes(f"avatar-{i}".encode())


def test_relative_avatar_resolves_against_project_root_not_capcut(tmp_path):
    project = tmp_path / "Projects" / "demo"
    project.mkdir(parents=True)
    resolved = resolve_asset_reference(project, "avatars/c1.mp4")
    assert resolved == (project / "avatars" / "c1.mp4").resolve()
    assert resolved != (project / "capcut" / "avatars" / "c1.mp4").resolve()


def test_absolute_avatar_path_remains_supported(tmp_path):
    avatar = (tmp_path / "external" / "c1.mp4").resolve()
    avatar.parent.mkdir(); avatar.write_bytes(b"x")
    assert resolve_asset_reference(tmp_path / "project", str(avatar)) == avatar


def test_windows_and_forward_slashes_resolve_to_same_project_asset(tmp_path):
    project = tmp_path / "project"
    assert resolve_asset_reference(project, r"avatars\c1.mp4") == resolve_asset_reference(project, "avatars/c1.mp4")


def test_avatar_chunks_are_once_each_and_v1_a1_are_exactly_aligned(tmp_path):
    project = make_project(tmp_path, 8)
    # Authoritative total = 10 seconds; scene display timing is not used for base media source offsets.
    write_avatar_manifest(project, [2.111111, 1.888889, 2.5, 1.25, 2.25])
    create_avatar_files(project, 5)
    result = export_capcut_project(project, build_timeline_manifest(project).manifest_path)
    draft = json.loads((result.project_dir / "draft_content.json").read_text())
    tracks = {track["name"]: track for track in draft["tracks"]}
    v1 = tracks["V1 Avatar"]["segments"]
    a1 = tracks["A1 Avatar Audio"]["segments"]
    assert len(v1) == len(a1) == 5
    assert [s["target_timerange"] for s in v1] == [s["target_timerange"] for s in a1]
    assert [s["source_timerange"] for s in v1] == [s["source_timerange"] for s in a1]
    assert all(s["source_timerange"]["start"] == 0 for s in v1)
    assert v1[-1]["target_timerange"]["start"] + v1[-1]["target_timerange"]["duration"] == 10_000_000
    assert draft["duration"] == 10_000_000
    report = (project / "capcut" / "export_report.md").read_text()
    assert "Maximum V1/A1 sync difference: 0 microseconds" in report
    assert "Avatar chunks on V1: 5" in report
    assert "Avatar chunks on A1: 5" in report


def test_scene_crossing_c1_to_c2_does_not_split_base_track(tmp_path):
    project = make_project(tmp_path, 2)
    # Keep scene metadata crossing a boundary while base track remains only c1,c2.
    path = project / "08_actual_timeline.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    rows[0]["Avatar Chunk"] = "c1.mp4 to c2.mp4"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
    write_avatar_manifest(project, [1.25, 1.25])
    create_avatar_files(project, 2)
    manifest = json.loads(build_timeline_manifest(project).manifest_path.read_text())
    assert manifest["scenes"][0]["assets"]["avatar"]["references"] == ["avatars/c1.mp4", "avatars/c2.mp4"]
    result = export_capcut_project(project)
    draft = json.loads((result.project_dir / "draft_content.json").read_text())
    tracks = {track["name"]: track for track in draft["tracks"]}
    assert len(tracks["V1 Avatar"]["segments"]) == 2
    assert len(tracks["A1 Avatar Audio"]["segments"]) == 2


def test_required_avatar_missing_fails_precisely(tmp_path):
    project = make_project(tmp_path, 3)
    write_avatar_manifest(project, [1.25, 1.25, 1.25])
    create_avatar_files(project, 3)
    (project / "avatars" / "c2.mp4").unlink()
    manifest = build_timeline_manifest(project).manifest_path
    with pytest.raises(CapCutExportError, match="Missing required avatar assets"):
        export_capcut_project(project, manifest)
    report = (project / "capcut" / "export_report.md").read_text()
    assert "BASE:c2.mp4" in report
    assert "Reference: `avatars/c2.mp4`" in report
    assert "Exists: No" in report


def test_only_assigned_image_and_broll_slots_get_visible_placeholders(tmp_path):
    project = make_project(tmp_path, 6)
    write_avatar_manifest(project, [7.5])
    create_avatar_files(project, 1)
    write_production_sheet(project, {
        "S001": "AI_IMAGE", "S002": "AVATAR", "S003": "STOCK_VIDEO",
        "S004": "OVERLAY", "S005": "AI_IMAGE", "S006": "STOCK_VIDEO",
    })
    result = export_capcut_project(project, build_timeline_manifest(project).manifest_path)
    draft = json.loads((result.project_dir / "draft_content.json").read_text())
    tracks = {track["name"]: track for track in draft["tracks"]}
    assert len(tracks["V2 Images"]["segments"]) == 2
    assert len(tracks["V3 B-roll"]["segments"]) == 2
    assert (project / "assets/placeholders/images/image_001.png").is_file()
    assert (project / "assets/placeholders/images/image_002.png").is_file()
    assert (project / "assets/placeholders/broll/broll_001.png").is_file()
    assert (project / "assets/placeholders/broll/broll_002.png").is_file()
    assert not (project / "assets/placeholders/images/image_003.png").exists()
    assets = json.loads((project / "capcut" / "asset_manifest.json").read_text())
    assert assets["image_assignment_count"] == 2
    assert assets["broll_assignment_count"] == 2
    assert assets["image_placeholders_remaining"] == 2
    assert assets["broll_placeholders_remaining"] == 2
    assert assets["final_assets_ready"] is False
    report = (project / "capcut" / "export_report.md").read_text()
    assert "Status: **PROJECT GENERATED / PREVIEW READY**" in report


def test_real_visual_assets_replace_placeholders_on_rerun(tmp_path):
    project = make_project(tmp_path, 3)
    write_avatar_manifest(project, [3.75]); create_avatar_files(project, 1)
    write_production_sheet(project, {"S001": "AI_IMAGE", "S002": "STOCK_VIDEO", "S003": "AVATAR"})
    manifest = build_timeline_manifest(project).manifest_path
    export_capcut_project(project, manifest)
    (project / "assets/images").mkdir(parents=True, exist_ok=True)
    (project / "assets/broll").mkdir(parents=True, exist_ok=True)
    (project / "assets/images/image_001.png").write_bytes(b"real-image")
    (project / "assets/broll/broll_001.mp4").write_bytes(b"real-broll")
    result = export_capcut_project(project, manifest)
    draft = json.loads((result.project_dir / "draft_content.json").read_text())
    material_paths = {Path(item["path"]) for item in draft["materials"]["videos"]}
    assert (project / "assets/images/image_001.png").resolve() in material_paths
    assert (project / "assets/broll/broll_001.mp4").resolve() in material_paths
    assets = json.loads((project / "capcut" / "asset_manifest.json").read_text())
    assert assets["image_placeholders_remaining"] == 0
    assert assets["broll_placeholders_remaining"] == 0
    assert assets["final_assets_ready"] is True
    report = (project / "capcut" / "export_report.md").read_text()
    assert "Status: **FINAL ASSETS READY**" in report


def test_visual_slot_timing_comes_from_actual_timeline_unchanged(tmp_path):
    project = make_project(tmp_path, 4)
    write_avatar_manifest(project, [5.0]); create_avatar_files(project, 1)
    write_production_sheet(project, {"S002": "AI_IMAGE", "S004": "STOCK_VIDEO"})
    manifest_path = build_timeline_manifest(project).manifest_path
    manifest = json.loads(manifest_path.read_text())
    result = export_capcut_project(project, manifest_path)
    draft = json.loads((result.project_dir / "draft_content.json").read_text())
    tracks = {track["name"]: track for track in draft["tracks"]}
    image_scene = next(s for s in manifest["scenes"] if s["scene_id"] == "S002")
    broll_scene = next(s for s in manifest["scenes"] if s["scene_id"] == "S004")
    assert tracks["V2 Images"]["segments"][0]["target_timerange"] == {
        "start": round(image_scene["timing"]["start_seconds"] * 1_000_000),
        "duration": round(image_scene["timing"]["duration_seconds"] * 1_000_000),
    }
    assert tracks["V3 B-roll"]["segments"][0]["target_timerange"] == {
        "start": round(broll_scene["timing"]["start_seconds"] * 1_000_000),
        "duration": round(broll_scene["timing"]["duration_seconds"] * 1_000_000),
    }


def test_capcut_87_complete_project_structure_uuid_relationships_and_mirrors(tmp_path):
    project = make_project(tmp_path, 2)
    write_avatar_manifest(project, [2.5]); create_avatar_files(project, 1)
    result = export_capcut_project(project, build_timeline_manifest(project).manifest_path)
    draft_dir = result.project_dir
    required_files = {
        "draft_content.json", "draft_meta_info.json", "draft_agency_config.json", "draft_biz_config.json",
        "attachment_pc_common.json", "performance_opt_info.json", "timeline_layout.json", "draft_settings", "template-2.tmp",
    }
    assert all((draft_dir / name).is_file() for name in required_files)
    for name in ("Resources", "Timelines", "subdraft", "adjust_mask", "common_attachment", "matting", "smart_crop", "qr_upload"):
        assert (draft_dir / name).is_dir()
    draft = json.loads((draft_dir / "draft_content.json").read_text())
    meta = json.loads((draft_dir / "draft_meta_info.json").read_text())
    layout = json.loads((draft_dir / "timeline_layout.json").read_text())
    settings = json.loads((draft_dir / "draft_settings").read_text())
    timeline_file = draft_dir / layout["timelines"][0]["path"]
    assert timeline_file.read_bytes() == (draft_dir / "draft_content.json").read_bytes()
    assert (draft_dir / "template-2.tmp").read_bytes() == (draft_dir / "draft_content.json").read_bytes()
    assert draft["id"] == meta["draft_id"] == layout["draft_id"] == settings["draft_id"]
    assert draft["timeline_id"] == meta["timeline_id"] == layout["active_timeline_id"] == settings["active_timeline_id"]
    assert draft["platform"]["app_version"] == "8.7.0"


def test_repeated_exports_are_deterministic(tmp_path):
    project = make_project(tmp_path, 4)
    write_avatar_manifest(project, [2.0, 3.0]); create_avatar_files(project, 2)
    write_production_sheet(project, {"S001": "AI_IMAGE", "S003": "STOCK_VIDEO"})
    manifest = build_timeline_manifest(project).manifest_path
    first_dir = export_capcut_project(project, manifest).project_dir
    first = {str(p.relative_to(first_dir)): p.read_bytes() for p in first_dir.rglob("*") if p.is_file()}
    first_placeholders = {str(p.relative_to(project)): p.read_bytes() for p in (project / "assets/placeholders").rglob("*") if p.is_file()}
    second_dir = export_capcut_project(project, manifest).project_dir
    second = {str(p.relative_to(second_dir)): p.read_bytes() for p in second_dir.rglob("*") if p.is_file()}
    second_placeholders = {str(p.relative_to(project)): p.read_bytes() for p in (project / "assets/placeholders").rglob("*") if p.is_file()}
    assert first == second
    assert first_placeholders == second_placeholders


def _native_scale_keyframes(segment):
    groups = segment.get("common_keyframes", [])
    scale_groups = [g for g in groups if g.get("property_type") == "KFTypeScaleX"]
    assert len(scale_groups) == 1
    assert scale_groups[0]["material_id"] == ""
    return scale_groups[0]["keyframe_list"]


def test_ai_image_motion_alternates_by_assignment_order_and_preserves_timing(tmp_path):
    project = make_project(tmp_path, 8)
    write_avatar_manifest(project, [10.0]); create_avatar_files(project, 1)
    write_production_sheet(project, {
        "S001": "AI_IMAGE",
        "S002": "STOCK_VIDEO",
        "S003": "AI_IMAGE",
        "S004": "AVATAR",
        "S005": "AI_IMAGE",
        "S006": "STOCK_VIDEO",
        "S007": "AI_IMAGE",
        "S008": "AVATAR",
    })
    manifest_path = build_timeline_manifest(project).manifest_path
    manifest = json.loads(manifest_path.read_text())
    expected_images = [s for s in manifest["scenes"] if isinstance(s.get("visual_assignment"), dict) and s["visual_assignment"].get("kind") == "image"]

    result = export_capcut_project(project, manifest_path)
    draft = json.loads((result.project_dir / "draft_content.json").read_text())
    tracks = {track["name"]: track for track in draft["tracks"]}
    images = tracks["V2 Images"]["segments"]
    assert len(images) == 4

    expected_scales = [(1.0, 1.08), (1.08, 1.0), (1.0, 1.08), (1.08, 1.0)]
    for segment, scene, (start_scale, end_scale) in zip(images, expected_images, expected_scales):
        expected_range = {
            "start": round(scene["timing"]["start_seconds"] * 1_000_000),
            "duration": round(scene["timing"]["duration_seconds"] * 1_000_000),
        }
        assert segment["target_timerange"] == expected_range
        assert segment["source_timerange"] == {"start": 0, "duration": expected_range["duration"]}
        frames = _native_scale_keyframes(segment)
        assert [f["time_offset"] for f in frames] == [0, expected_range["duration"]]
        assert [f["values"] for f in frames] == [[start_scale], [end_scale]]
        assert [f["curveType"] for f in frames] == ["FreeCurveInOut", "Line"]
        assert all(f["graphID"] == "" and f["string_value"] == "" for f in frames)
        assert all(f["left_control"] == {"x": 0.0, "y": 0.0} for f in frames)
        assert frames[0]["right_control"]["x"] == expected_range["duration"] * 0.32
        assert frames[0]["right_control"]["y"] == (end_scale - start_scale) * 0.94
        assert frames[1]["right_control"] == {"x": 0.0, "y": 0.0}
        assert segment["uniform_scale"] == {"on": True, "value": 1.0}
        assert segment["keyframe_refs"] == []
        assert segment["clip"]["scale"] == {"x": end_scale, "y": end_scale}
        assert segment["clip"]["transform"] == {"x": 0.0, "y": 0.0}


def test_ai_image_zoom_matches_real_capcut_87_reference_pattern(tmp_path):
    project = make_project(tmp_path, 4)
    write_avatar_manifest(project, [5.0]); create_avatar_files(project, 1)
    write_production_sheet(project, {f"S{i:03d}": "AI_IMAGE" for i in range(1, 5)})
    result = export_capcut_project(project, build_timeline_manifest(project).manifest_path)
    draft = json.loads((result.project_dir / "draft_content.json").read_text())
    images = next(t for t in draft["tracks"] if t["name"] == "V2 Images")["segments"]
    assert len(images) == 4
    expected_pairs = [(1.0, 1.08), (1.08, 1.0), (1.0, 1.08), (1.08, 1.0)]
    for segment, (start_scale, end_scale) in zip(images, expected_pairs):
        frames = _native_scale_keyframes(segment)
        duration = segment["target_timerange"]["duration"]
        assert segment["keyframe_refs"] == []
        assert segment["uniform_scale"] == {"on": True, "value": 1.0}
        assert segment["clip"]["scale"] == {"x": end_scale, "y": end_scale}
        assert frames[0] == {
            "curveType": "FreeCurveInOut",
            "graphID": "",
            "id": frames[0]["id"],
            "left_control": {"x": 0.0, "y": 0.0},
            "right_control": {"x": duration * 0.32, "y": (end_scale - start_scale) * 0.94},
            "string_value": "",
            "time_offset": 0,
            "values": [start_scale],
        }
        assert frames[1] == {
            "curveType": "Line",
            "graphID": "",
            "id": frames[1]["id"],
            "left_control": {"x": 0.0, "y": 0.0},
            "right_control": {"x": 0.0, "y": 0.0},
            "string_value": "",
            "time_offset": duration,
            "values": [end_scale],
        }


def test_broll_gets_no_automatic_ai_image_zoom(tmp_path):
    project = make_project(tmp_path, 4)
    write_avatar_manifest(project, [5.0]); create_avatar_files(project, 1)
    write_production_sheet(project, {
        "S001": "STOCK_VIDEO", "S002": "AI_IMAGE", "S003": "STOCK_VIDEO", "S004": "AI_IMAGE",
    })
    result = export_capcut_project(project, build_timeline_manifest(project).manifest_path)
    draft = json.loads((result.project_dir / "draft_content.json").read_text())
    tracks = {track["name"]: track for track in draft["tracks"]}
    assert len(tracks["V3 B-roll"]["segments"]) == 2
    assert all("common_keyframes" not in segment for segment in tracks["V3 B-roll"]["segments"])
    assert all("common_keyframes" in segment for segment in tracks["V2 Images"]["segments"])


def test_ai_image_motion_does_not_touch_avatar_audio_segment_metadata(tmp_path):
    project = make_project(tmp_path, 4)
    write_avatar_manifest(project, [2.0, 3.0]); create_avatar_files(project, 2)
    write_production_sheet(project, {"S001": "AI_IMAGE", "S003": "AI_IMAGE"})
    result = export_capcut_project(project, build_timeline_manifest(project).manifest_path)
    draft = json.loads((result.project_dir / "draft_content.json").read_text())
    tracks = {track["name"]: track for track in draft["tracks"]}
    v1 = tracks["V1 Avatar"]["segments"]
    a1 = tracks["A1 Avatar Audio"]["segments"]
    assert [s["target_timerange"] for s in v1] == [
        {"start": 0, "duration": 2_000_000}, {"start": 2_000_000, "duration": 3_000_000}
    ]
    assert [s["target_timerange"] for s in a1] == [s["target_timerange"] for s in v1]
    assert [s["source_timerange"] for s in a1] == [s["source_timerange"] for s in v1]
    assert all("common_keyframes" not in segment for segment in v1 + a1)


def test_ai_image_placeholder_keeps_intended_zoom_metadata(tmp_path):
    project = make_project(tmp_path, 2)
    write_avatar_manifest(project, [2.5]); create_avatar_files(project, 1)
    write_production_sheet(project, {"S001": "AI_IMAGE", "S002": "AI_IMAGE"})
    result = export_capcut_project(project, build_timeline_manifest(project).manifest_path)
    draft = json.loads((result.project_dir / "draft_content.json").read_text())
    images = next(t for t in draft["tracks"] if t["name"] == "V2 Images")["segments"]
    assert [_native_scale_keyframes(s)[0]["values"] for s in images] == [[1.0], [1.08]]
    assert [_native_scale_keyframes(s)[1]["values"] for s in images] == [[1.08], [1.0]]


def test_repeated_exports_keep_alternating_ai_image_keyframes_byte_identical(tmp_path):
    project = make_project(tmp_path, 6)
    write_avatar_manifest(project, [7.5]); create_avatar_files(project, 1)
    write_production_sheet(project, {
        "S001": "AI_IMAGE", "S002": "STOCK_VIDEO", "S003": "AI_IMAGE",
        "S004": "AVATAR", "S005": "AI_IMAGE", "S006": "AI_IMAGE",
    })
    manifest = build_timeline_manifest(project).manifest_path
    first_dir = export_capcut_project(project, manifest).project_dir
    first = (first_dir / "draft_content.json").read_bytes()
    second_dir = export_capcut_project(project, manifest).project_dir
    second = (second_dir / "draft_content.json").read_bytes()
    assert first == second
    draft = json.loads(second.decode("utf-8"))
    images = next(t for t in draft["tracks"] if t["name"] == "V2 Images")["segments"]
    assert [(_native_scale_keyframes(s)[0]["values"][0], _native_scale_keyframes(s)[1]["values"][0]) for s in images] == [
        (1.0, 1.08), (1.08, 1.0), (1.0, 1.08), (1.08, 1.0)
    ]


def test_export_report_lists_native_ai_image_motion_diagnostics(tmp_path):
    project = make_project(tmp_path, 3)
    write_avatar_manifest(project, [4.68]); create_avatar_files(project, 1)
    write_production_sheet(project, {"S001": "AI_IMAGE", "S002": "AI_IMAGE", "S003": "AI_IMAGE"})
    export_capcut_project(project, build_timeline_manifest(project).manifest_path)
    report = (project / "capcut" / "export_report.md").read_text()
    assert "AI image motion: native common_keyframes / KFTypeScaleX + uniform_scale lock" in report
    assert "### image_001.png" in report
    assert "- Motion: ZOOM_IN" in report
    assert "- Start scale: 1.00" in report
    assert "- End scale: 1.08" in report
    assert "### image_002.png" in report
    assert "- Motion: ZOOM_OUT" in report
    assert "- Start scale: 1.08" in report
    assert "- End scale: 1.00" in report
    assert "- CapCut keyframe count: 2" in report

def _write_overlay_rows(project, rows):
    fields=["overlay_id","overlay_number","start_seconds","end_seconds","duration_seconds","overlay_text","overlay_type","script_line_start","script_line_end","timing_source","status","priority"]
    with (project / "11_text_overlays.csv").open("w", encoding="utf-8-sig", newline="") as h:
        w=csv.DictWriter(h,fieldnames=fields); w.writeheader(); w.writerows(rows)


def _compound_main_text(draft, parent_segment):
    drafts={d["id"]:d for d in draft["materials"]["drafts"]}
    outer=next(drafts[x] for x in parent_segment["extra_material_refs"] if x in drafts)
    outer_draft=outer["draft"]
    inner_seg=next(s for t in outer_draft["tracks"] if t["type"]=="video" for s in t["segments"])
    inner=next(drafts[x] for x in inner_seg["extra_material_refs"] if x in drafts)
    text_draft=inner["draft"]
    main=next(m for m in text_draft["materials"]["texts"] if m.get("font_path")=="C:/Windows/Fonts/Figtree-Bold.ttf")
    main_seg=next(s for t in text_draft["tracks"] if t["type"]=="text" for s in t["segments"] if s["material_id"]==main["id"])
    return outer, inner, inner_seg, text_draft, main, main_seg


def test_validated_text_overlay_uses_live_verified_compound_and_resolved_timing(tmp_path):
    project = make_project(tmp_path, 3)
    write_avatar_manifest(project, [3.75]); create_avatar_files(project, 1)
    write_production_sheet(project, {"S001": "AI_IMAGE", "S002": "STOCK_VIDEO", "S003": "AVATAR"})
    _write_overlay_rows(project,[{
        "overlay_id":"OVL001","overlay_number":1,"start_seconds":0.5,"end_seconds":2.0,"duration_seconds":1.5,
        "overlay_text":"MEASURE FIRST | THEN OBSERVE","overlay_type":"ACTION","script_line_start":"Scene 1","script_line_end":"Scene 2",
        "timing_source":"word_timestamps","status":"READY","priority":100}])
    result=export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    draft=json.loads((result.project_dir / "draft_content.json").read_text())
    tracks={t["name"]:t for t in draft["tracks"]}
    overlay_track=tracks["Text Overlay Compounds"]
    assert overlay_track["type"] == "video"
    parent=overlay_track["segments"][0]
    assert parent["target_timerange"] == {"start":500000,"duration":1500000}
    outer,inner,inner_seg,text_draft,main,main_seg=_compound_main_text(draft,parent)
    assert json.loads(main["content"])["text"] == "MEASURE FIRST\nTHEN OBSERVE"
    assert main["font_path"] == "C:/Windows/Fonts/Figtree-Bold.ttf"
    assert main["font_size"] == 15.0 and main["text_color"] == "#ffffff" and main["alignment"] == 1
    assert main_seg["clip"]["scale"] == {"x":0.748803277623793,"y":0.748803277623793}
    assert main_seg["clip"]["transform"] == {"x":0.0,"y":-0.695754716981132}
    lanes={k["property_type"]:k for k in inner_seg["common_keyframes"]}
    assert set(lanes) >= {"KFTypePositionX","KFTypePositionY"}
    assert lanes["KFTypePositionX"]["keyframe_list"][1]["time_offset"] == 366666
    assert lanes["KFTypePositionY"]["keyframe_list"][1]["time_offset"] == 366666
    assert lanes["KFTypePositionX"]["keyframe_list"][0]["right_control"]["x"] == 202666.0
    assert lanes["KFTypePositionX"]["keyframe_list"][1]["left_control"]["x"] == -253334.0
    assert lanes["KFTypePositionY"]["keyframe_list"][0]["values"] == [-0.6470588235294117]
    assert lanes["KFTypePositionY"]["keyframe_list"][1]["values"] == [0.04235294117647059]
    audit=json.loads((project/"capcut"/"text_overlay_compound_audit.json").read_text())
    assert audit["details"][0]["physical_paths_resolve"] is True
    assert audit["details"][0]["subdrafts"][0]["content_exists"] is True
    assert audit["details"][0]["subdrafts"][0]["config_exists"] is True
    assert audit["details"][0]["subdrafts"][0]["cover_exists"] is True
    assert audit["details"][0]["subdrafts"][1]["content_exists"] is True
    assert audit["details"][0]["subdrafts"][1]["config_exists"] is True
    assert audit["details"][0]["subdrafts"][1]["cover_exists"] is True
    assert len(tracks["V1 Avatar"]["segments"]) == 1
    assert len(tracks["A1 Avatar Audio"]["segments"]) == 1
    assert len(tracks["V2 Images"]["segments"]) == 1
    assert len(tracks["V3 B-roll"]["segments"]) == 1


def test_multiple_compound_overlays_are_unique_white_figtree_and_all_physical_payloads_exist(tmp_path):
    project = make_project(tmp_path, 3)
    write_avatar_manifest(project, [3.75]); create_avatar_files(project, 1)
    write_production_sheet(project, {"S001": "AI_IMAGE", "S002": "STOCK_VIDEO", "S003": "AVATAR"})
    rows=[
        {"overlay_id":"OVL001","overlay_number":1,"start_seconds":0.5,"end_seconds":1.5,"duration_seconds":1.0,"overlay_text":"LEVEL SPOON | ≈ 95 CALORIES","overlay_type":"NUMBER","script_line_start":"Scene 1","script_line_end":"Scene 1","timing_source":"word_timestamps","status":"READY","priority":100},
        {"overlay_id":"OVL002","overlay_number":2,"start_seconds":1.5,"end_seconds":2.5,"duration_seconds":1.0,"overlay_text":"PEANUT ALLERGY | FIRM AVOID","overlay_type":"SAFETY","script_line_start":"Scene 2","script_line_end":"Scene 2","timing_source":"word_timestamps","status":"READY","priority":100},
        {"overlay_id":"OVL003","overlay_number":3,"start_seconds":2.5,"end_seconds":3.5,"duration_seconds":1.0,"overlay_text":"FOOD | NOT A TREATMENT","overlay_type":"TAKEAWAY","script_line_start":"Scene 3","script_line_end":"Scene 3","timing_source":"word_timestamps","status":"READY","priority":100},
    ]
    _write_overlay_rows(project,rows)
    result=export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    draft=json.loads((result.project_dir / "draft_content.json").read_text())
    track=next(t for t in draft["tracks"] if t["name"]=="Text Overlay Compounds")
    assert [s["target_timerange"] for s in track["segments"]] == [
        {"start":500000,"duration":1000000},{"start":1500000,"duration":1000000},{"start":2500000,"duration":1000000}]
    assert len(draft["materials"]["drafts"]) == 6
    parent_ids={s["id"] for s in track["segments"]}
    assert len(parent_ids)==3
    rendered=[]
    combo_ids=set()
    for parent in track["segments"]:
        outer,inner,inner_seg,text_draft,main,main_seg=_compound_main_text(draft,parent)
        combo_ids.update([outer["id"],inner["id"]])
        rendered.append(json.loads(main["content"])["text"])
        assert main["font_size"]==15.0 and main["text_color"]=="#ffffff" and main["alignment"]==1
        assert any(json.loads(m["content"])["text"]=="------------------------" for m in text_draft["materials"]["texts"])
        # Root JSON uses CapCut-native draft-root placeholder paths; the audit
        # resolves them to the same authoritative physical subdraft records.
        assert outer["draft_file_path"].startswith("##_draftpath_placeholder_")
        assert inner["draft_file_path"].startswith("##_draftpath_placeholder_")
    assert len(combo_ids)==6
    assert rendered == ["LEVEL SPOON\n≈ 95 CALORIES","PEANUT ALLERGY\nFIRM AVOID","FOOD\nNOT A TREATMENT"]
    audit=json.loads((project/"capcut"/"text_overlay_compound_audit.json").read_text())
    assert audit["generated_compound_overlays"]==3
    assert audit["physical_subdraft_folders"]==6
    assert audit["dangling_reference_count"]==0
    assert audit["duplicate_id_occurrences"]==0


def test_all_47_ready_overlays_export_as_47_unique_compounds_and_94_subdrafts(tmp_path):
    project = make_project(tmp_path, 47)
    write_avatar_manifest(project, [58.75]); create_avatar_files(project, 1)
    write_production_sheet(project, {f"S{i:03d}": "AVATAR" for i in range(1,48)})
    rows=[]
    for i in range(47):
        start=i*1.25
        rows.append({
            "overlay_id":f"OVL{i+1:03d}","overlay_number":i+1,
            "start_seconds":start,"end_seconds":start+1.0,"duration_seconds":1.0,
            "overlay_text":f"OVERLAY {i+1} | VERIFIED","overlay_type":"TAKEAWAY",
            "script_line_start":f"Scene {i+1}","script_line_end":f"Scene {i+1}",
            "timing_source":"word_timestamps","status":"READY","priority":100,
        })
    _write_overlay_rows(project,rows)
    result=export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    draft=json.loads((result.project_dir/"draft_content.json").read_text())
    track=next(t for t in draft["tracks"] if t["name"]=="Text Overlay Compounds")
    assert len(track["segments"])==47
    assert len(draft["materials"]["drafts"])==94
    audit=json.loads((project/"capcut"/"text_overlay_compound_audit.json").read_text())
    assert audit["generated_compound_overlays"]==47
    assert audit["physical_subdraft_folders"]==94
    assert audit["dangling_reference_count"]==0
    assert audit["reference_uuid_reuse_count"]==0
    assert audit["duplicate_id_occurrences"]==0
    assert len({s["id"] for s in track["segments"]})==47
    assert len(list((result.project_dir/"subdraft").iterdir()))==94
    layout=json.loads((result.project_dir/"timeline_layout.json").read_text())
    timeline_id=layout["active_timeline_id"]
    timeline_file=result.project_dir/"Timelines"/timeline_id/"draft_content.json"
    assert timeline_file.is_file()
    assert timeline_file.read_bytes()==(result.project_dir/"draft_content.json").read_bytes()
    physical=json.loads((project/"capcut"/"physical_file_audit.json").read_text())
    assert physical["timeline_id"]==timeline_id
    assert physical["missing_referenced_physical_paths"]==0


def test_compound_subdraft_paths_use_same_uuid_for_metadata_and_physical_directory(tmp_path):
    project = make_project(tmp_path, 1)
    write_avatar_manifest(project, [1.25]); create_avatar_files(project, 1)
    _write_overlay_rows(project,[{
        "overlay_id":"OVL001","overlay_number":1,"start_seconds":0.0,"end_seconds":1.0,"duration_seconds":1.0,
        "overlay_text":"MEASURE FIRST | THEN OBSERVE","overlay_type":"ACTION",
        "script_line_start":"Scene 1","script_line_end":"Scene 1",
        "timing_source":"word_timestamps","status":"READY","priority":100}])
    result=export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    audit=json.loads((project/"capcut"/"text_overlay_compound_audit.json").read_text())
    assert audit["expected_physical_subdraft_folders"]==2
    assert audit["physical_subdraft_folders"]==2
    assert audit["missing_physical_subdraft_folders"]==0
    for sd in audit["details"][0]["subdrafts"]:
        physical=Path(sd["physical_directory"])
        assert physical.name == sd["generated_subdraft_id"]
        assert f"\\subdraft\\{sd['generated_subdraft_id']}\\draft_content.json" in sd["referenced_path"]
        assert sd["content_exists"] and sd["config_exists"] and sd["cover_exists"]


def test_packaging_is_called_only_after_all_subdraft_files_exist(tmp_path, monkeypatch):
    project = make_project(tmp_path, 2)
    write_avatar_manifest(project, [2.5]); create_avatar_files(project, 1)
    _write_overlay_rows(project,[
        {"overlay_id":"OVL001","overlay_number":1,"start_seconds":0.0,"end_seconds":1.0,"duration_seconds":1.0,
         "overlay_text":"ONE | READY","overlay_type":"ACTION","script_line_start":"Scene 1","script_line_end":"Scene 1",
         "timing_source":"word_timestamps","status":"READY","priority":100},
        {"overlay_id":"OVL002","overlay_number":2,"start_seconds":1.0,"end_seconds":2.0,"duration_seconds":1.0,
         "overlay_text":"TWO | READY","overlay_type":"ACTION","script_line_start":"Scene 2","script_line_end":"Scene 2",
         "timing_source":"word_timestamps","status":"READY","priority":100},
    ])
    real_bundle=capcut_export._create_capcut_87_bundle
    observed={"called":False}
    def checked_bundle(draft_dir, **kwargs):
        subdirs=[p for p in (Path(draft_dir)/"subdraft").iterdir() if p.is_dir()]
        assert len(subdirs)==4
        for sd in subdirs:
            assert (sd/"draft_content.json").is_file()
            assert (sd/"sub_draft_config.json").is_file()
            assert (sd/"draft_cover.jpg").is_file()
        observed["called"]=True
        return real_bundle(draft_dir, **kwargs)
    monkeypatch.setattr(capcut_export, "_create_capcut_87_bundle", checked_bundle)
    export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    assert observed["called"] is True



def test_one_overlay_timeline_id_and_physical_mirror_are_consistent(tmp_path):
    project=make_project(tmp_path,1)
    write_avatar_manifest(project,[1.25]); create_avatar_files(project,1)
    _write_overlay_rows(project,[{
        "overlay_id":"OVL001","overlay_number":1,"start_seconds":0.0,"end_seconds":1.0,"duration_seconds":1.0,
        "overlay_text":"MEASURE FIRST | THEN OBSERVE","overlay_type":"ACTION",
        "script_line_start":"Scene 1","script_line_end":"Scene 1",
        "timing_source":"word_timestamps","status":"READY","priority":100}])
    result=export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    draft=json.loads((result.project_dir/"draft_content.json").read_text())
    meta=json.loads((result.project_dir/"draft_meta_info.json").read_text())
    layout=json.loads((result.project_dir/"timeline_layout.json").read_text())
    settings=json.loads((result.project_dir/"draft_settings").read_text())
    tid=draft["timeline_id"]
    assert tid==meta["timeline_id"]==layout["active_timeline_id"]==layout["timelines"][0]["id"]==settings["active_timeline_id"]
    assert meta["timeline_path"]==layout["timelines"][0]["path"]==f"Timelines/{tid}/draft_content.json"
    timeline_file=result.project_dir/"Timelines"/tid/"draft_content.json"
    assert timeline_file.is_file()
    assert timeline_file.read_bytes()==(result.project_dir/"draft_content.json").read_bytes()
    # Existing proven compound physical payload remains intact.
    audit=json.loads((project/"capcut"/"text_overlay_compound_audit.json").read_text())
    assert audit["physical_subdraft_folders"]==2
    assert audit["missing_physical_subdraft_folders"]==0


def test_timeline_physical_audit_runs_only_after_timeline_file_is_written(tmp_path, monkeypatch):
    project=make_project(tmp_path,1)
    write_avatar_manifest(project,[1.25]); create_avatar_files(project,1)
    manifest=build_timeline_manifest(project).manifest_path
    real_audit=capcut_export._audit_capcut_physical_files
    observed={"called":False}
    def checked_audit(*,draft_dir,timeline_id,generated_compounds):
        timeline_file=Path(draft_dir)/"Timelines"/timeline_id/"draft_content.json"
        assert timeline_file.is_file()
        assert (Path(draft_dir)/"draft_content.json").is_file()
        observed["called"]=True
        return real_audit(draft_dir=Path(draft_dir),timeline_id=timeline_id,generated_compounds=generated_compounds)
    monkeypatch.setattr(capcut_export,"_audit_capcut_physical_files",checked_audit)
    export_capcut_project(project,manifest)
    assert observed["called"] is True


def test_repeated_overlay_export_keeps_timeline_references_internally_consistent(tmp_path):
    project=make_project(tmp_path,1)
    write_avatar_manifest(project,[1.25]); create_avatar_files(project,1)
    _write_overlay_rows(project,[{
        "overlay_id":"OVL001","overlay_number":1,"start_seconds":0.0,"end_seconds":1.0,"duration_seconds":1.0,
        "overlay_text":"ONE | OVERLAY","overlay_type":"TAKEAWAY",
        "script_line_start":"Scene 1","script_line_end":"Scene 1",
        "timing_source":"word_timestamps","status":"READY","priority":100}])
    manifest=build_timeline_manifest(project).manifest_path
    for _ in range(2):
        result=export_capcut_project(project,manifest)
        draft=json.loads((result.project_dir/"draft_content.json").read_text())
        layout=json.loads((result.project_dir/"timeline_layout.json").read_text())
        tid=draft["timeline_id"]
        assert layout["active_timeline_id"]==tid
        assert layout["timelines"][0]["id"]==tid
        assert (result.project_dir/"Timelines"/tid/"draft_content.json").is_file()
        compound=json.loads((project/"capcut"/"text_overlay_compound_audit.json").read_text())
        assert compound["missing_physical_subdraft_folders"]==0
        physical=json.loads((project/"capcut"/"physical_file_audit.json").read_text())
        assert physical["missing_referenced_physical_paths"]==0



def test_nested_figtree_content_unwraps_accidental_rich_text_payload_once(tmp_path):
    project=make_project(tmp_path,1)
    write_avatar_manifest(project,[1.25]); create_avatar_files(project,1)

    reference=json.loads(capcut_export.TEXT_OVERLAY_REFERENCE_JSON.read_text(encoding="utf-8"))
    _,outer,_,inner_seg,inner=capcut_export._find_compound_chain(reference)
    text_draft=inner["draft"]
    reference_main=next(
        m for m in text_draft["materials"]["texts"]
        if m.get("font_path")=="C:/Windows/Fonts/Figtree-Bold.ttf"
    )
    # Reproduce the live failure: an already-complete CapCut rich-text JSON
    # payload arrives where only visible text is expected.
    _write_overlay_rows(project,[{
        "overlay_id":"OVL001","overlay_number":1,"start_seconds":0.0,"end_seconds":1.0,"duration_seconds":1.0,
        "overlay_text":reference_main["content"],"overlay_type":"TAKEAWAY",
        "script_line_start":"Scene 1","script_line_end":"Scene 1",
        "timing_source":"word_timestamps","status":"READY","priority":100}])

    result=export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    draft=json.loads((result.project_dir/"draft_content.json").read_text())
    track=next(t for t in draft["tracks"] if t["name"]=="Text Overlay Compounds")
    _,_,_,text_draft,main,main_seg=_compound_main_text(draft,track["segments"][0])

    parsed=json.loads(main["content"])
    assert isinstance(parsed,dict)
    assert isinstance(parsed["text"],str)
    assert parsed["text"]=="COFFEE\nAND BLOOD SUGAR"
    assert not parsed["text"].lstrip().startswith('{"text":')
    assert not parsed["text"].lstrip().startswith('{\\"text\\":')
    assert not parsed["text"].lstrip().startswith('{"styles":')
    assert parsed["styles"][0]["range"]==[0,len("COFFEE\nAND BLOOD SUGAR")]
    assert parsed["styles"][0]["font"]["path"]=="C:/Windows/Fonts/Figtree-Bold.ttf"
    assert parsed["styles"][0]["size"]==15
    assert parsed["styles"][0]["bold"] is True
    assert main["font_size"]==15.0
    assert main["text_color"]=="#ffffff"
    assert main["alignment"]==1
    assert main_seg["clip"]["scale"]=={"x":0.748803277623793,"y":0.748803277623793}
    assert main_seg["clip"]["transform"]=={"x":0.0,"y":-0.695754716981132}

    separator=next(m for m in text_draft["materials"]["texts"] if m["id"]!=main["id"])
    separator_parsed=json.loads(separator["content"])
    assert isinstance(separator_parsed,dict)
    assert separator_parsed["text"]=="------------------------"

    # Both physical compound payload levels still exist and the physical audit passes.
    compound=json.loads((project/"capcut"/"text_overlay_compound_audit.json").read_text())
    assert compound["missing_physical_subdraft_folders"]==0
    assert compound["dangling_reference_count"]==0
    physical=json.loads((project/"capcut"/"physical_file_audit.json").read_text())
    assert physical["missing_referenced_physical_paths"]==0


def test_plain_overlay_text_remains_single_encoded_rich_text_json(tmp_path):
    project=make_project(tmp_path,1)
    write_avatar_manifest(project,[1.25]); create_avatar_files(project,1)
    _write_overlay_rows(project,[{
        "overlay_id":"OVL001","overlay_number":1,"start_seconds":0.0,"end_seconds":1.0,"duration_seconds":1.0,
        "overlay_text":"COFFEE | AND BLOOD SUGAR","overlay_type":"TAKEAWAY",
        "script_line_start":"Scene 1","script_line_end":"Scene 1",
        "timing_source":"word_timestamps","status":"READY","priority":100}])
    result=export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    draft=json.loads((result.project_dir/"draft_content.json").read_text())
    parent=next(t for t in draft["tracks"] if t["name"]=="Text Overlay Compounds")["segments"][0]
    _,_,_,text_draft,main,_=_compound_main_text(draft,parent)
    parsed=json.loads(main["content"])
    assert parsed["text"]=="COFFEE\nAND BLOOD SUGAR"
    assert parsed["styles"][0]["range"]==[0,22]
    separator=next(m for m in text_draft["materials"]["texts"] if m["id"]!=main["id"])
    assert json.loads(separator["content"])["text"]=="------------------------"


def test_export_tolerates_draft_folder_disappearing_during_reset(tmp_path, monkeypatch):
    project = make_project(tmp_path, 2)
    write_avatar_manifest(project, [1.25, 1.25])
    create_avatar_files(project, 2)
    built = build_timeline_manifest(project, project / "08_actual_timeline.csv")
    draft_dir = project / "capcut" / "CapCut_Project"
    draft_dir.mkdir(parents=True, exist_ok=True)
    (draft_dir / "stale.tmp").write_text("stale", encoding="utf-8")

    real_rmtree = shutil.rmtree
    calls = {"count": 0}

    def disappearing_rmtree(path, *args, **kwargs):
        if Path(path) == draft_dir and calls["count"] == 0:
            calls["count"] += 1
            real_rmtree(path)
            raise FileNotFoundError(2, "No such file or directory", str(path))
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(capcut_export.shutil, "rmtree", disappearing_rmtree)
    result = export_capcut_project(project, built.manifest_path)
    assert result.success is True
    assert (draft_dir / "draft_content.json").is_file()


def test_live_visible_text_is_not_serialized_rich_text_payload_and_fonts_keep_native_paths(tmp_path):
    project=make_project(tmp_path,1)
    write_avatar_manifest(project,[1.25]); create_avatar_files(project,1)
    _write_overlay_rows(project,[{
        "overlay_id":"OVL001","overlay_number":1,"start_seconds":0.0,"end_seconds":1.0,"duration_seconds":1.0,
        "overlay_text":"COFFEE AND BLOOD SUGAR","overlay_type":"TAKEAWAY",
        "script_line_start":"Scene 1","script_line_end":"Scene 1",
        "timing_source":"word_timestamps","status":"READY","priority":100}])
    result=export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    root=json.loads((result.project_dir/"draft_content.json").read_text())
    parent=next(t for t in root["tracks"] if t["name"]=="Text Overlay Compounds")["segments"][0]
    _,_,_,text_draft,main,_=_compound_main_text(root,parent)

    # Native CapCut 8.7: content is one JSON-encoded string; the visible text is
    # the decoded content.text value, never the serialized rich-text payload.
    assert isinstance(main["content"],str)
    assert "text" not in main
    body=json.loads(main["content"])
    assert body["text"]=="COFFEE AND BLOOD SUGAR"
    assert body["text"] != main["content"]
    assert not body["text"].lstrip().startswith('{"text":')
    assert body["styles"][0]["range"]==[0,22]
    assert main["font_path"]=="C:/Windows/Fonts/Figtree-Bold.ttf"
    assert body["styles"][0]["font"]["path"]==main["font_path"]

    separator=next(m for m in text_draft["materials"]["texts"] if m["id"]!=main["id"])
    separator_body=json.loads(separator["content"])
    assert separator["font_path"]=="C:/Windows/Fonts/impact.ttf"
    assert separator_body["styles"][0]["font"]["path"]==separator["font_path"]

    # The same semantics must reach the physical Timeline and both physical
    # compound subdrafts, not merely the in-memory/root representation.
    timeline_id=root["timeline_id"]
    physical_root=json.loads((result.project_dir/"Timelines"/timeline_id/"draft_content.json").read_text())
    pparent=next(t for t in physical_root["tracks"] if t["name"]=="Text Overlay Compounds")["segments"][0]
    _,_,_,ptext_draft,pmain,_=_compound_main_text(physical_root,pparent)
    assert json.loads(pmain["content"])["text"]=="COFFEE AND BLOOD SUGAR"
    assert pmain["font_path"]=="C:/Windows/Fonts/Figtree-Bold.ttf"

    physical=json.loads((project/"capcut"/"physical_file_audit.json").read_text())
    assert physical["missing_referenced_physical_paths"]==0


def test_capcut_87_root_uses_native_content_schema_version_for_rich_text():
    """Root and nested text drafts must use the same native 8.7 content schema discriminator."""
    from capcut_export import CAPCUT_APP_VERSION, CAPCUT_NATIVE_NEW_VERSION
    assert CAPCUT_APP_VERSION == "8.7.0"
    assert CAPCUT_NATIVE_NEW_VERSION == "171.0.0"

    reference = json.loads((Path(__file__).resolve().parents[1] / "Templates" / "capcut_text_overlay" / "compound_reference.json").read_text(encoding="utf-8"))
    assert reference["new_version"] == CAPCUT_NATIVE_NEW_VERSION
    for combo in reference["materials"]["drafts"]:
        assert combo["draft"]["new_version"] == CAPCUT_NATIVE_NEW_VERSION

    text_draft = next(
        combo["draft"] for combo in reference["materials"]["drafts"]
        if combo["draft"].get("materials", {}).get("texts")
    )
    main = next(m for m in text_draft["materials"]["texts"] if m.get("font_path") == "C:/Windows/Fonts/Figtree-Bold.ttf")
    body = json.loads(main["content"])
    assert body["text"] == "COFFEE \nAND BLOOD SUGAR"
    assert body["text"] != main["content"]
    assert not body["text"].startswith('{"text":')


def test_text_overlay_visual_polish_type_colors_background_and_frozen_contract(tmp_path):
    from copy import deepcopy
    from capcut_export import (
        TEXT_OVERLAY_TYPE_STYLES, TEXT_OVERLAY_BACKGROUND_OPACITY,
        TEXT_OVERLAY_MAIN_COLOR, _find_compound_chain,
    )
    project=make_project(tmp_path,8)
    write_avatar_manifest(project,[10.0]); create_avatar_files(project,1)
    types=["NUMBER","KEY FACT","MYTH CHECK","CONTRAST","ACTION","SAFETY","TAKEAWAY","UNKNOWN"]
    rows=[]
    for i,typ in enumerate(types):
        rows.append({
            "overlay_id":f"OVL{i+1:03d}","overlay_number":i+1,
            "start_seconds":i+0.05,"end_seconds":i+0.80,"duration_seconds":0.75,
            "overlay_text":f"TYPE {i+1} | VISUAL ONLY","overlay_type":typ,
            "script_line_start":f"Scene {i+1}","script_line_end":f"Scene {i+1}",
            "timing_source":"word_timestamps","status":"READY","priority":100,
        })
    _write_overlay_rows(project,rows)

    # Freeze the native animation/geometry before export. IDs are remapped normally,
    # so compare the non-ID semantic structures after stripping UUID-bearing ids.
    reference=json.loads((Path(__file__).resolve().parents[1]/"Templates"/"capcut_text_overlay"/"compound_reference.json").read_text())
    _,_,native_outer,native_inner_seg,native_inner= _find_compound_chain(reference)
    native_text=native_inner["draft"]
    native_main=next(m for m in native_text["materials"]["texts"] if m.get("font_path")=="C:/Windows/Fonts/Figtree-Bold.ttf")
    native_main_seg=next(s for t in native_text["tracks"] if t["type"]=="text" for s in t["segments"] if s["material_id"]==native_main["id"])
    frozen_main_clip=deepcopy(native_main_seg["clip"])
    frozen_inner_keyframes=deepcopy(native_inner_seg["common_keyframes"])

    result=export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    draft=json.loads((result.project_dir/"draft_content.json").read_text())
    track=next(t for t in draft["tracks"] if t["name"]=="Text Overlay Compounds")
    assert len(track["segments"])==8
    expected={k:v["accent"] for k,v in TEXT_OVERLAY_TYPE_STYLES.items()}
    expected["UNKNOWN"]="#FFD400"

    def strip_ids(obj):
        if isinstance(obj,dict):
            return {k:strip_ids(v) for k,v in obj.items() if k not in {"id","graphID"}}
        if isinstance(obj,list): return [strip_ids(x) for x in obj]
        return obj

    for parent,typ,row in zip(track["segments"],types,rows):
        _,_,inner_seg,text_draft,main,main_seg=_compound_main_text(draft,parent)
        separator=next(m for m in text_draft["materials"]["texts"] if m.get("font_path")=="C:/Windows/Fonts/impact.ttf")
        main_body=json.loads(main["content"]); sep_body=json.loads(separator["content"])
        assert main_body["text"]==row["overlay_text"].replace(" | ","\n")
        assert main["font_path"]=="C:/Windows/Fonts/Figtree-Bold.ttf"
        assert main_body["styles"][0]["font"]["path"]==main["font_path"]
        assert main["alignment"]==1
        assert main["text_color"]==TEXT_OVERLAY_MAIN_COLOR.lower()
        assert main["global_alpha"]==1.0 and main["text_alpha"]==1.0
        assert main_body["styles"][0]["fill"]["content"]["solid"]["color"]==[1,1,1]
        assert separator["font_path"]=="C:/Windows/Fonts/impact.ttf"
        assert sep_body["styles"][0]["font"]["path"]==separator["font_path"]
        assert separator["text_color"]==expected[typ].lower()
        assert separator["background_color"]=="#000000"
        assert separator["background_alpha"]==TEXT_OVERLAY_BACKGROUND_OPACITY==0.75
        assert separator["global_alpha"]==1.0 and separator["text_alpha"]==1.0
        assert main_seg["clip"]==frozen_main_clip
        # Durations are intentionally authoritative per overlay, but animation shape,
        # properties, controls, and linkage stay native. Compare the opening animation
        # keyframes excluding generated IDs and duration-dependent terminal offsets.
        got=strip_ids(inner_seg["common_keyframes"])
        ref=strip_ids(frozen_inner_keyframes)
        assert [x["property_type"] for x in got]==[x["property_type"] for x in ref]
        for g,r in zip(got,ref):
            assert g["keyframe_list"][0]["values"]==r["keyframe_list"][0]["values"]
            assert g["keyframe_list"][0]["curveType"]==r["keyframe_list"][0]["curveType"]

    assert draft["materials"]["stickers"]==[]
    assert all("common_keyframes" in s for t in draft["tracks"] if t["name"]=="V2 Images" for s in t["segments"])


def _write_mixed_overlay_rows(project, rows):
    fields = ["overlay_id","overlay_number","start_seconds","end_seconds","duration_seconds","overlay_class",
              "overlay_text","overlay_type","heading","bullet_1","bullet_2","bullet_3","source_trace","claim_key",
              "script_line_start","script_line_end","timing_source","status","priority"]
    with (project / "11_text_overlays.csv").open("w", encoding="utf-8-sig", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields); w.writeheader(); w.writerows(rows)


def _evidence_row(number=1, start=0.4, end=1.4, heading="RESEARCH FINDING", bullets=None):
    bullets = bullets or ["Adults age 60+", "12-week controlled study", "Was associated with better mobility"]
    return {
        "overlay_id": f"EVD{number:03d}", "overlay_number": number, "start_seconds": start,
        "end_seconds": end, "duration_seconds": end-start, "overlay_class": "EVIDENCE",
        "overlay_text": "", "overlay_type": "KEY FACT", "heading": heading,
        "bullet_1": bullets[0], "bullet_2": bullets[1], "bullet_3": bullets[2],
        "source_trace": '{"project":"fixture"}', "claim_key": f"claim-{number}",
        "script_line_start": f"Scene {number}", "script_line_end": f"Scene {number}",
        "timing_source": "word_timestamps", "status": "READY", "priority": 200,
    }


def _standard_row(number=1, start=0.0, end=0.3):
    return {
        "overlay_id": f"OVL{number:03d}", "overlay_number": number, "start_seconds": start,
        "end_seconds": end, "duration_seconds": end-start, "overlay_class": "STANDARD",
        "overlay_text": "STANDARD | TEXT", "overlay_type": "KEY FACT", "heading": "",
        "bullet_1": "", "bullet_2": "", "bullet_3": "", "source_trace": "", "claim_key": "",
        "script_line_start": f"Scene {number}", "script_line_end": f"Scene {number}",
        "timing_source": "word_timestamps", "status": "READY", "priority": 100,
    }


def _evidence_materials(draft, parent):
    drafts = {d["id"]: d for d in draft["materials"]["drafts"]}
    outer = next(drafts[x] for x in parent["extra_material_refs"] if x in drafts)
    outer_draft = outer["draft"]
    inner_seg = next(s for t in outer_draft["tracks"] if t["type"] == "video" for s in t["segments"])
    inner = next(drafts[x] for x in inner_seg["extra_material_refs"] if x in drafts)
    heading = next(m for m in outer_draft["materials"]["texts"] if m.get("font_path") == "C:/Windows/Fonts/Figtree-Bold.ttf")
    body = next(m for m in outer_draft["materials"]["texts"] if m.get("font_path") == "C:/Windows/Fonts/arial.ttf")
    separator = next(m for m in inner["draft"]["materials"]["texts"] if m.get("font_path") == "C:/Windows/Fonts/impact.ttf")
    return outer, inner, inner_seg, heading, body, separator


def test_phase3_zero_evidence_does_not_load_template_or_create_t2(tmp_path, monkeypatch):
    project = make_project(tmp_path, 2); write_avatar_manifest(project, [2.5]); create_avatar_files(project, 1)
    _write_mixed_overlay_rows(project, [_standard_row()])
    monkeypatch.setattr(capcut_export, "_load_evidence_overlay_master", lambda: (_ for _ in ()).throw(AssertionError("must not load")))
    result = export_capcut_project(project, build_timeline_manifest(project).manifest_path)
    draft = json.loads((result.project_dir / "draft_content.json").read_text())
    names = [t["name"] for t in draft["tracks"]]
    assert "Text Overlay Compounds" in names and "Evidence Card Compounds" not in names
    assert "Evidence template loads this export: 0" in (project / "capcut" / "export_report.md").read_text()


def test_phase3_one_evidence_generates_t2_and_full_physical_chain(tmp_path):
    project = make_project(tmp_path, 2); write_avatar_manifest(project, [2.5]); create_avatar_files(project, 1)
    _write_mixed_overlay_rows(project, [_evidence_row()])
    result = export_capcut_project(project, build_timeline_manifest(project).manifest_path)
    draft = json.loads((result.project_dir / "draft_content.json").read_text())
    t2 = next(t for t in draft["tracks"] if t["name"] == "Evidence Card Compounds")
    assert len(t2["segments"]) == 1 and t2["segments"][0]["target_timerange"] == {"start":400000,"duration":1000000}
    audit = json.loads((project / "capcut" / "evidence_overlay_compound_audit.json").read_text())
    assert audit["generated_evidence_overlays"] == 1 and audit["physical_subdraft_folders"] == 2
    detail = audit["details"][0]
    assert Path(detail["outer_subdraft"], "draft_content.json").is_file()
    assert Path(detail["inner_subdraft"], "draft_content.json").is_file()
    for folder in (Path(detail["outer_subdraft"]), Path(detail["inner_subdraft"])):
        assert (folder / "sub_draft_config.json").is_file() and (folder / "draft_cover.jpg").is_file()


def test_phase3_multiple_evidence_clones_have_unique_ids(tmp_path):
    project=make_project(tmp_path,4); write_avatar_manifest(project,[5.0]); create_avatar_files(project,1)
    _write_mixed_overlay_rows(project,[_evidence_row(1,.4,1.4),_evidence_row(2,1.7,2.7),_evidence_row(3,3.0,4.0)])
    result=export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    draft=json.loads((result.project_dir/"draft_content.json").read_text())
    t2=next(t for t in draft["tracks"] if t["name"]=="Evidence Card Compounds")
    assert len({s["id"] for s in t2["segments"]})==3
    audit=json.loads((project/"capcut"/"evidence_overlay_compound_audit.json").read_text())
    assert audit["duplicate_id_occurrences"]==0 and audit["reference_uuid_reuse_count"]==0


def test_phase3_heading_and_three_bullets_substitute_exactly(tmp_path):
    project=make_project(tmp_path,2); write_avatar_manifest(project,[2.5]); create_avatar_files(project,1)
    row=_evidence_row(1,.4,1.6,"BMJ STUDY (2019)",["58,769 cases","225,574 controls","Was linked to 49% higher risk"])
    _write_mixed_overlay_rows(project,[row]); result=export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    draft=json.loads((result.project_dir/"draft_content.json").read_text()); parent=next(t for t in draft["tracks"] if t["name"]=="Evidence Card Compounds")["segments"][0]
    _,_,_,heading,body,separator=_evidence_materials(draft,parent)
    assert json.loads(heading["content"])["text"]==row["heading"]
    assert json.loads(body["content"])["text"]=="• 58,769 cases\n• 225,574 controls\n• Was linked to 49% higher risk"
    assert json.loads(separator["content"])["text"]=="------------------------"


def test_phase3_preserves_canonical_timing_and_reference_entrance_animation(tmp_path):
    project=make_project(tmp_path,3); write_avatar_manifest(project,[3.75]); create_avatar_files(project,1)
    row=_evidence_row(1,.625,2.0); _write_mixed_overlay_rows(project,[row])
    result=export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    draft=json.loads((result.project_dir/"draft_content.json").read_text()); parent=next(t for t in draft["tracks"] if t["name"]=="Evidence Card Compounds")["segments"][0]
    _,_,inner_seg,_,_,_=_evidence_materials(draft,parent)
    assert parent["target_timerange"]=={"start":625000,"duration":1375000}
    lanes={x["property_type"]:x for x in inner_seg["common_keyframes"]}
    assert lanes["KFTypePositionY"]["keyframe_list"][0]["values"]==[-0.6470588235294117]
    assert lanes["KFTypePositionY"]["keyframe_list"][1]["values"]==[0.04235294117647059]
    assert lanes["KFTypePositionY"]["keyframe_list"][1]["time_offset"]==366666


def test_phase3_sanitized_template_and_generated_payloads_have_no_source_machine_paths(tmp_path):
    template=(Path(capcut_export.EVIDENCE_OVERLAY_REFERENCE_JSON)).read_text().replace("\\\\","/")
    assert "C:/Users/Dell/AppData/" not in template and "D:/capcuts/" not in template
    project=make_project(tmp_path,2); write_avatar_manifest(project,[2.5]); create_avatar_files(project,1); _write_mixed_overlay_rows(project,[_evidence_row()])
    result=export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    for p in (result.project_dir/"subdraft").rglob("*.json"):
        raw=p.read_text().replace("\\\\","/")
        assert "C:/Users/Dell/AppData/" not in raw and "D:/capcuts/" not in raw


def test_phase3_long_project_path_generates_evidence_subdrafts(tmp_path):
    long_root=tmp_path/('segment_'+'a'*60)/('segment_'+'b'*60)/('segment_'+'c'*60)
    long_root.mkdir(parents=True)
    project=make_project(long_root,2); write_avatar_manifest(project,[2.5]); create_avatar_files(project,1); _write_mixed_overlay_rows(project,[_evidence_row()])
    result=export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    assert (result.project_dir/"draft_content.json").is_file()
    assert len([p for p in (result.project_dir/"subdraft").iterdir() if p.is_dir()])==2


def test_phase3_missing_template_hard_fails_only_with_evidence(tmp_path, monkeypatch):
    project=make_project(tmp_path,2); write_avatar_manifest(project,[2.5]); create_avatar_files(project,1); _write_mixed_overlay_rows(project,[_evidence_row()])
    monkeypatch.setattr(capcut_export,"EVIDENCE_OVERLAY_REFERENCE_JSON",tmp_path/"missing.json")
    with pytest.raises(CapCutExportError,match="Missing sanitized Evidence Overlay template"):
        export_capcut_project(project,build_timeline_manifest(project).manifest_path)


def test_phase3_malformed_template_hard_fails(tmp_path, monkeypatch):
    malformed=tmp_path/"bad.json"; malformed.write_text('{"tracks":[],"materials":{"drafts":[]}}')
    (tmp_path/"p").mkdir()
    project=make_project(tmp_path/"p",2); write_avatar_manifest(project,[2.5]); create_avatar_files(project,1); _write_mixed_overlay_rows(project,[_evidence_row()])
    monkeypatch.setattr(capcut_export,"EVIDENCE_OVERLAY_REFERENCE_JSON",malformed)
    with pytest.raises(CapCutExportError,match="compound chain"):
        export_capcut_project(project,build_timeline_manifest(project).manifest_path)


def test_phase3_unremapped_reference_uuid_is_caught(tmp_path, monkeypatch):
    from copy import deepcopy
    project=make_project(tmp_path,2); write_avatar_manifest(project,[2.5]); create_avatar_files(project,1); _write_mixed_overlay_rows(project,[_evidence_row()])
    monkeypatch.setattr(capcut_export,"_remap_reference_uuids",lambda payload:(deepcopy(payload),{}))
    with pytest.raises(CapCutExportError,match="Evidence UUID isolation failure"):
        export_capcut_project(project,build_timeline_manifest(project).manifest_path)


def test_phase3_surviving_standard_evidence_overlap_hard_fails(tmp_path):
    project=make_project(tmp_path,2); write_avatar_manifest(project,[2.5]); create_avatar_files(project,1)
    _write_mixed_overlay_rows(project,[_standard_row(1,.2,.8),_evidence_row(1,.4,1.4)])
    with pytest.raises(CapCutExportError,match="collision survived Phase 1/2"):
        export_capcut_project(project,build_timeline_manifest(project).manifest_path)


def test_phase3_surviving_evidence_evidence_overlap_hard_fails(tmp_path):
    project=make_project(tmp_path,2); write_avatar_manifest(project,[2.5]); create_avatar_files(project,1)
    _write_mixed_overlay_rows(project,[_evidence_row(1,.3,1.3),_evidence_row(2,1.0,2.0)])
    with pytest.raises(CapCutExportError,match="collision survived Phase 1/2"):
        export_capcut_project(project,build_timeline_manifest(project).manifest_path)


def test_phase3_legacy_standard_only_artifact_still_exports_without_t2(tmp_path):
    project=make_project(tmp_path,2); write_avatar_manifest(project,[2.5]); create_avatar_files(project,1)
    _write_overlay_rows(project,[{"overlay_id":"OVL001","overlay_number":1,"start_seconds":0.1,"end_seconds":0.9,"duration_seconds":0.8,"overlay_text":"LEGACY | STANDARD","overlay_type":"KEY FACT","script_line_start":"Scene 1","script_line_end":"Scene 1","timing_source":"word_timestamps","status":"READY","priority":100}])
    result=export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    draft=json.loads((result.project_dir/"draft_content.json").read_text())
    tracks={t["name"]:t for t in draft["tracks"]}
    assert len(tracks["Text Overlay Compounds"]["segments"])==1 and "Evidence Card Compounds" not in tracks


def test_phase3_end_to_end_mixed_structural_bundle_passes_without_changing_underlying_timing(tmp_path):
    project=make_project(tmp_path,5); write_avatar_manifest(project,[6.25]); create_avatar_files(project,1)
    write_production_sheet(project,{"S001":"AI_IMAGE","S002":"STOCK_VIDEO","S003":"AVATAR","S004":"AI_IMAGE","S005":"STOCK_VIDEO"})
    rows=[_standard_row(1,.05,.30),_evidence_row(1,.45,1.45),_standard_row(2,1.55,1.85),_evidence_row(2,2.0,3.0)]
    _write_mixed_overlay_rows(project,rows)
    manifest_path=build_timeline_manifest(project).manifest_path
    manifest=json.loads(manifest_path.read_text())
    result=export_capcut_project(project,manifest_path)
    draft=json.loads((result.project_dir/"draft_content.json").read_text()); tracks={t["name"]:t for t in draft["tracks"]}
    assert len(tracks["Text Overlay Compounds"]["segments"])==2 and len(tracks["Evidence Card Compounds"]["segments"])==2
    assert len(tracks["V1 Avatar"]["segments"])==1 and len(tracks["A1 Avatar Audio"]["segments"])==1
    assert len(tracks["V2 Images"]["segments"])==2 and len(tracks["V3 B-roll"]["segments"])==2
    assert tracks["V1 Avatar"]["segments"][0]["target_timerange"]=={"start":0,"duration":6250000}
    assert json.loads((project/"capcut"/"evidence_overlay_compound_audit.json").read_text())["generated_evidence_overlays"]==2
    assert json.loads((project/"capcut"/"physical_file_audit.json").read_text())["missing_referenced_physical_paths"]==0
    capcut_export.validate_capcut_87_bundle(result.project_dir)


def test_phase3_evidence_template_load_count_is_one_for_multiple_cards(tmp_path, monkeypatch):
    project=make_project(tmp_path,4); write_avatar_manifest(project,[5.0]); create_avatar_files(project,1)
    _write_mixed_overlay_rows(project,[_evidence_row(1,.4,1.4),_evidence_row(2,1.7,2.7),_evidence_row(3,3.0,4.0)])
    real=capcut_export._load_evidence_overlay_master; calls={"n":0}
    def counted(): calls["n"]+=1; return real()
    monkeypatch.setattr(capcut_export,"_load_evidence_overlay_master",counted)
    export_capcut_project(project,build_timeline_manifest(project).manifest_path)
    assert calls["n"]==1
    assert "Evidence template loads this export: 1" in (project/"capcut"/"export_report.md").read_text()

def test_canonical_img_br_asset_names_are_discovered_and_used(tmp_path):
    project = make_project(tmp_path, 3)
    write_avatar_manifest(project, [3.75]); create_avatar_files(project, 1)
    write_production_sheet(project, {"S001": "AI_IMAGE", "S002": "STOCK_VIDEO", "S003": "AVATAR"})
    # Production/Opus convention uses prompt IDs rather than legacy image_001/broll_001 names.
    rows = list(csv.DictReader((project / "07_production_sheet.csv").open(encoding="utf-8", newline="")))
    rows[0]["image_prompt_id"] = "IMG001"
    rows[1]["broll_prompt_id"] = "BR001"
    with (project / "07_production_sheet.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
    (project / "assets/images").mkdir(parents=True, exist_ok=True)
    (project / "assets/broll").mkdir(parents=True, exist_ok=True)
    (project / "assets/images/IMG001.png").write_bytes(b"real-image")
    (project / "assets/broll/BR001.mp4").write_bytes(b"real-broll")
    manifest = build_timeline_manifest(project).manifest_path
    payload = json.loads(manifest.read_text())
    assigned = {s["scene_id"]: s.get("visual_assignment") for s in payload["scenes"]}
    assert assigned["S001"]["reference"] == "assets/images/IMG001.png"
    assert assigned["S002"]["reference"] == "assets/broll/BR001.mp4"
    result = export_capcut_project(project, manifest)
    assets = json.loads((project / "capcut/asset_manifest.json").read_text())
    assert assets["image_placeholders_remaining"] == 0
    assert assets["broll_placeholders_remaining"] == 0
    assert assets["final_assets_ready"] is True
