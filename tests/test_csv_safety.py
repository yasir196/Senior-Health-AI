import csv
from pathlib import Path

import pytest

from avatar_timing import load_production_scenes
from csv_safety import (
    SPREADSHEET_ERROR_VALUES,
    protect_spreadsheet_text,
    recover_spreadsheet_text,
    validate_script_text,
)
from timeline_builder import TimelineBuildError, build_timeline_manifest


@pytest.mark.parametrize("text", ["=- text", "+ text", "- text", "@ text"])
def test_formula_like_text_round_trips_without_visible_change(text):
    protected = protect_spreadsheet_text(text)
    assert protected == "'" + text
    assert recover_spreadsheet_text(protected) == text


def test_normal_narration_is_unchanged():
    text = "Normal narration"
    assert protect_spreadsheet_text(text) == text
    assert recover_spreadsheet_text(text) == text


@pytest.mark.parametrize("error", sorted(SPREADSHEET_ERROR_VALUES))
def test_all_spreadsheet_errors_are_rejected(error):
    with pytest.raises(ValueError) as exc:
        validate_script_text(error, "S064")
    assert str(exc.value) == f"Scene S064 contains spreadsheet-corrupted script text: {error}"


def test_production_sheet_reader_recovers_protective_quote(tmp_path: Path):
    sheet = tmp_path / "07_production_sheet.csv"
    with sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scene_id", "script_excerpt"])
        writer.writeheader()
        writer.writerow({"scene_id": "S064", "script_excerpt": "'=- about olive oil"})
    assert load_production_scenes(sheet)[0]["script_text"] == "=- about olive oil"


def test_production_sheet_reader_rejects_corrupted_text(tmp_path: Path):
    sheet = tmp_path / "07_production_sheet.csv"
    with sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scene_id", "script_excerpt"])
        writer.writeheader()
        writer.writerow({"scene_id": "S064", "script_excerpt": "#NAME?"})
    with pytest.raises(ValueError, match=r"Scene S064 contains spreadsheet-corrupted script text: #NAME\?"):
        load_production_scenes(sheet)


def test_timeline_reader_recovers_quote_and_rejects_errors(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    path = project / "08_actual_timeline.csv"
    fields = ["Scene ID", "Script Text", "Actual Audio Start", "Actual Audio End", "Duration", "Avatar Chunk", "Timing Source"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"Scene ID":"S064","Script Text":"'=@ text","Actual Audio Start":"00:00.0","Actual Audio End":"00:04.5","Duration":"4.48","Avatar Chunk":"c1.mp4","Timing Source":"TRANSCRIPT"})
    result = build_timeline_manifest(project)
    import json
    data = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert data["scenes"][0]["narration_text"] == "=@ text"

    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    rows[0]["Script Text"] = "#VALUE!"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    with pytest.raises(TimelineBuildError, match=r"Scene S064 contains spreadsheet-corrupted script text: #VALUE!"):
        build_timeline_manifest(project)
