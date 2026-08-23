from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "Projects" / "after-70-daily-routines-balance-independence"
PRODUCTION_SHEET = PROJECT / "07_production_sheet.csv"


REQUIRED_COLUMNS = [
    "scene_id",
    "start_time",
    "end_time",
    "duration_sec",
    "scene_purpose",
    "script_excerpt",
    "visual_mode",
    "avatar_required",
    "avatar_style",
    "background_style",
    "image_prompt_id",
    "broll_prompt_id",
    "narrative_context",
    "visual_intent",
    "filmable",
    "asset_decision_reason",
    "asset_search_query",
    "alternative_search_query_1",
    "alternative_search_query_2",
    "ai_image_prompt",
    "overlay_instruction",
    "recommended_asset_type",
    "recommended_shot",
    "manual_search_notes",
    "avoid_results",
    "asset_source",
    "selected_asset_path",
    "asset_status",
    "motion",
    "transition",
    "on_screen_text",
    "notes",
]

ASSET_STATUS = {
    "STOCK_VIDEO": "TO_FIND",
    "STOCK_IMAGE": "TO_FIND",
    "AI_IMAGE": "GENERATE",
    "AVATAR": "READY",
    "OVERLAY": "DESIGN",
    "SPLIT_SCREEN": "TO_ASSEMBLE",
    "NO_ASSET_NEEDED": "NOT_NEEDED",
}


def load_rows():
    with PRODUCTION_SHEET.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_production_sheet_has_narrative_planning_schema() -> None:
    with PRODUCTION_SHEET.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == REQUIRED_COLUMNS


def test_every_scene_has_required_planning_fields_and_asset_status() -> None:
    for row in load_rows():
        assert row["narrative_context"].strip(), row["scene_id"]
        assert row["visual_intent"].strip(), row["scene_id"]
        assert row["filmable"] in {"YES", "NO", "PARTIAL"}
        assert row["asset_decision_reason"].strip(), row["scene_id"]
        assert row["recommended_asset_type"] in ASSET_STATUS
        assert row["asset_status"] == ASSET_STATUS[row["recommended_asset_type"]]


def test_stock_rows_have_concrete_queries_and_manual_search_notes() -> None:
    stock_types = {"STOCK_VIDEO", "STOCK_IMAGE"}
    for row in load_rows():
        if row["recommended_asset_type"] not in stock_types:
            continue
        query = row["asset_search_query"].lower()
        assert len(query.split()) >= 4, row["scene_id"]
        assert row["alternative_search_query_1"].strip(), row["scene_id"]
        assert row["alternative_search_query_2"].strip(), row["scene_id"]
        assert row["manual_search_notes"].strip(), row["scene_id"]
        assert row["avoid_results"].strip(), row["scene_id"]
        for abstract_word in ["curiosity", "motivation", "trust", "confidence", "concept", "evidence"]:
            assert abstract_word not in query.split(), row["scene_id"]


def test_lace_up_scene_uses_walking_not_stairs_or_unrelated_exercise() -> None:
    rows = {row["scene_id"]: row for row in load_rows()}
    row = rows["S002"]
    combined = " ".join(
        [
            row["narrative_context"],
            row["visual_intent"],
            row["asset_search_query"],
            row["alternative_search_query_1"],
            row["alternative_search_query_2"],
            row["manual_search_notes"],
        ]
    ).lower()
    assert "walking" in combined or "walk" in combined
    for forbidden in ["stairs", "stair", "chair", "physical therapist", "exercise class"]:
        assert forbidden not in combined

