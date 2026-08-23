from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path

import pytest

from image_generation import load_production_image_assignments
from opus_image_prompt_import import (
    build_image_prompts_markdown,
    load_production_ai_image_slots,
    normalize_script_line,
    parse_opus_csv,
    script_lines_match,
    validate_import,
    write_image_prompts,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_sheet(project: Path, rows: list[dict[str, str]]) -> Path:
    project.mkdir(parents=True, exist_ok=True)
    fields = [
        "scene_id", "start_time", "end_time", "duration_sec", "scene_purpose", "script_excerpt",
        "visual_mode", "avatar_required", "avatar_style", "background_style", "image_prompt_id",
        "broll_prompt_id", "narrative_context", "visual_intent", "filmable", "asset_decision_reason",
        "asset_search_query", "alternative_search_query_1", "alternative_search_query_2", "ai_image_prompt",
        "overlay_instruction", "recommended_asset_type", "recommended_shot", "manual_search_notes", "avoid_results",
        "asset_source", "selected_asset_path", "asset_status", "motion", "transition", "on_screen_text", "notes",
    ]
    path = project / "07_production_sheet.csv"
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields)
        w.writeheader()
        for row in rows:
            full = {k: "" for k in fields}; full.update(row); w.writerow(full)
    return path


def _base_rows() -> list[dict[str, str]]:
    return [
        {"scene_id":"S001","start_time":"00:01","end_time":"00:07","scene_purpose":"HOOK","script_excerpt":"If you're over 60, you've probably seen this advice.","image_prompt_id":"IMG-OLD-1","narrative_context":"Opening narration context.","recommended_asset_type":"AI_IMAGE","selected_asset_path":"assets/images/image_001.png"},
        {"scene_id":"S002","start_time":"00:07","end_time":"00:12","scene_purpose":"BRIDGE","script_excerpt":"This avatar row is not an image.","recommended_asset_type":"AVATAR"},
        {"scene_id":"S003","start_time":"00:12","end_time":"00:18","scene_purpose":"EXPLAIN","script_excerpt":"One tablespoon carries about 120 calories.","image_prompt_id":"IMG-OLD-2","narrative_context":"Calorie explanation context.","recommended_asset_type":"AI_IMAGE","selected_asset_path":"assets/images/image_002.png"},
    ]


def _opus(rows=None) -> bytes:
    rows = rows or [
        [1, '“If you’re over 60 — you’ve probably seen this advice.”', "Warm home kitchen scene with an older adult holding a measured spoon of olive oil.", "0:00 - 0:08", "Person/Character"],
        [2, "One tablespoon carries about 120 calories!", "Close food-detail scene showing one measured tablespoon beside an ordinary meal plate.", "9:99 - 9:99", "Food/Product Detail"],
    ]
    out = io.StringIO(newline="")
    w = csv.writer(out); w.writerow(["Image Number","Script Line","AI Image Prompt","Timing","Scene Type"]); w.writerows(rows)
    return out.getvalue().encode()


def test_production_output_remains_unchanged(tmp_path: Path):
    project = tmp_path / "P"; sheet = _write_sheet(project, _base_rows()); before = _sha(sheet)
    write_image_prompts(project, _opus())
    assert _sha(sheet) == before


def test_production_ai_image_rows_are_extracted_correctly(tmp_path: Path):
    project = tmp_path / "P"; _write_sheet(project, _base_rows())
    slots = load_production_ai_image_slots(project)
    assert [(s.image_number, s.scene_id) for s in slots] == [(1,"S001"),(2,"S003")]


def test_opus_timing_is_ignored_and_actual_timeline_wins(tmp_path: Path):
    project = tmp_path / "P"; _write_sheet(project, _base_rows())
    with (project/"08_actual_timeline.csv").open("w",encoding="utf-8",newline="") as h:
        w=csv.DictWriter(h,fieldnames=["Scene ID","Script Text","Actual Audio Start","Actual Audio End","Duration","Avatar Chunk","Timing Source"]); w.writeheader(); w.writerow({"Scene ID":"S001","Actual Audio Start":"00:00.500","Actual Audio End":"00:06.750"}); w.writerow({"Scene ID":"S003","Actual Audio Start":"00:11.900","Actual Audio End":"00:18.100"})
    text,_=build_image_prompts_markdown(project,_opus())
    assert "00:00.500 → 00:06.750" in text
    assert "9:99 - 9:99" not in text
    assert "0:00 - 0:08" not in text


def test_mapping_follows_image_number_and_production_assignment_order(tmp_path: Path):
    project=tmp_path/"P"; _write_sheet(project,_base_rows()); v=validate_import(project,_opus())
    assert v.passed
    assert [(m.image_number,m.scene_id) for m in v.mappings] == [(1,"S001"),(2,"S003")]
    assert "measured spoon" in v.mappings[0].prompt
    assert "120" in v.mappings[1].production_script_line


def test_script_line_normalization_accepts_harmless_punctuation_differences():
    a="If you're over 60, you've probably seen this advice."
    b='“If you’re over 60 — you’ve probably seen this advice!”'
    matched,score=script_lines_match(a,b)
    assert matched and score >= .90
    assert normalize_script_line("A—B") == normalize_script_line("A - B")


def test_real_script_mismatch_is_rejected(tmp_path: Path):
    project=tmp_path/"P"; _write_sheet(project,_base_rows())
    bad=_opus([[1,"Completely unrelated bedtime reflux narration.","Prompt A","0:00","X"],[2,"One tablespoon carries about 120 calories.","Prompt B","0:01","Y"]])
    v=validate_import(project,bad)
    assert not v.passed and v.mappings[0].match_status == "MISMATCH"


def test_count_mismatch_is_rejected(tmp_path: Path):
    project=tmp_path/"P"; _write_sheet(project,_base_rows())
    one=_opus([[1,"If you're over 60, you've probably seen this advice.","Prompt A","0:00","X"]])
    v=validate_import(project,one)
    assert not v.passed
    assert any("Count mismatch" in e for e in v.errors)


def test_duplicate_image_number_is_rejected():
    rows,errors=parse_opus_csv(_opus([[1,"a","p1","x",""],[1,"b","p2","x",""]]))
    assert len(rows)==2 and any("Duplicate Image Number" in e for e in errors)


def test_missing_image_number_is_rejected():
    _,errors=parse_opus_csv(_opus([[1,"a","p1","x",""],[3,"b","p2","x",""]]))
    assert any("Missing Image Number" in e for e in errors)


def test_non_numeric_and_out_of_order_image_numbers_are_rejected():
    _,errors=parse_opus_csv(_opus([[2,"a","p1","x",""],[1,"b","p2","x",""]]))
    assert any("out of order" in e for e in errors)
    _,errors2=parse_opus_csv(_opus([["one","a","p1","x",""]]))
    assert any("must be numeric" in e for e in errors2)


def test_final_prompt_equals_imported_opus_prompt_after_safe_cleanup(tmp_path: Path):
    project=tmp_path/"P"; _write_sheet(project,_base_rows())
    source=_opus([[1,"If you're over 60, you've probably seen this advice.","Subject â€” action   objects","legacy","Type A"],[2,"One tablespoon carries about 120 calories.","Exact second prompt","legacy","Type B"]])
    text,_=build_image_prompts_markdown(project,source)
    assert "Final AI IMAGE PROMPT: Subject — action objects" in text
    assert "Final AI IMAGE PROMPT: Exact second prompt" in text


def test_old_production_archetype_prompt_does_not_overwrite_imported_prompt(tmp_path: Path):
    project=tmp_path/"P"; _write_sheet(project,_base_rows())
    (project/"10_image_prompts.md").write_text("### IMAGE 001\n- Final AI IMAGE PROMPT: OLD REFLUX CHAIR ARCHETYPE\n",encoding="utf-8")
    text,_=build_image_prompts_markdown(project,_opus())
    assert "OLD REFLUX CHAIR ARCHETYPE" not in text
    assert "Warm home kitchen scene" in text


def test_generated_markdown_is_compatible_with_image_generation_agent(tmp_path: Path):
    project=tmp_path/"P"; _write_sheet(project,_base_rows()); write_image_prompts(project,_opus())
    assignments=load_production_image_assignments(project)
    assert len(assignments)==2
    assert assignments[0].filename=="image_001.png"
    assert assignments[1].filename=="image_002.png"
    assert assignments[0].original_prompt.startswith("Warm home kitchen scene")


def test_project_switching_isolates_output_paths(tmp_path: Path):
    a=tmp_path/"A"; b=tmp_path/"B"; _write_sheet(a,_base_rows()); _write_sheet(b,_base_rows())
    pa,_,_=write_image_prompts(a,_opus()); pb,_,_=write_image_prompts(b,_opus())
    assert pa == a/"10_image_prompts.md" and pb == b/"10_image_prompts.md"
    assert pa.resolve() != pb.resolve()


def test_existing_image_assets_are_untouched(tmp_path: Path):
    project=tmp_path/"P"; _write_sheet(project,_base_rows()); assets=project/"assets"/"images"; assets.mkdir(parents=True)
    img1=assets/"image_001.png"; img2=assets/"image_002.png"; img1.write_bytes(b"existing-one"); img2.write_bytes(b"existing-two")
    before=(_sha(img1),_sha(img2)); write_image_prompts(project,_opus()); after=(_sha(img1),_sha(img2))
    assert after==before


def test_existing_prompt_file_is_backed_up_before_replace(tmp_path: Path):
    project=tmp_path/"P"; _write_sheet(project,_base_rows()); old=project/"10_image_prompts.md"; old.write_text("old prompt file",encoding="utf-8")
    output,backup,_=write_image_prompts(project,_opus())
    assert output.is_file() and backup is not None and backup.is_file()
    assert backup.read_text(encoding="utf-8") == "old prompt file"


def test_output_uses_production_timing_when_actual_timeline_absent(tmp_path: Path):
    project=tmp_path/"P"; _write_sheet(project,_base_rows()); text,_=build_image_prompts_markdown(project,_opus())
    assert "Actual Timing: 00:01 → 00:07" in text
    assert "Actual Timing: 00:12 → 00:18" in text


def test_scene_type_is_optional(tmp_path: Path):
    project=tmp_path/"P"; _write_sheet(project,_base_rows())
    out=io.StringIO(newline=""); w=csv.writer(out); w.writerow(["Image Number","Script Line","AI Image Prompt"]); w.writerow([1,"If you're over 60, you've probably seen this advice.","P1"]); w.writerow([2,"One tablespoon carries about 120 calories.","P2"])
    text,v=build_image_prompts_markdown(project,out.getvalue().encode())
    assert v.passed and "- Scene Type: " in text
