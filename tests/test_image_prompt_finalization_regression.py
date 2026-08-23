import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "Projects" / "after-70-daily-routines-balance-independence"


def _sheet_assignments():
    rows = list(csv.DictReader((PROJECT / "07_production_sheet.csv").open(encoding="utf-8-sig")))
    out = []
    seen = set()
    for row in rows:
        pid = row.get("image_prompt_id", "").strip()
        is_ai = (row.get("recommended_asset_type") or row.get("asset_type") or "").strip().upper() == "AI_IMAGE"
        if is_ai and pid and pid not in seen:
            seen.add(pid)
            out.append(row)
    return out


def _prompt_blocks():
    text = (PROJECT / "10_image_prompts.md").read_text(encoding="utf-8")
    chunks = re.split(r"(?=^### IMAGE \d{3}$)", text, flags=re.M)[1:]
    return text, chunks


def test_regenerated_output_preserves_filename_count_scene_assignment_and_timing():
    sheet = _sheet_assignments()
    text, blocks = _prompt_blocks()
    assert len(sheet) == len(blocks)
    assert len(blocks) > 0
    for i, (row, block) in enumerate(zip(sheet, blocks), 1):
        assert f"Filename: image_{i:03d}.png" in block
        assert f"image_prompt_id: {row['image_prompt_id']}" in block
        assert f"Scene ID: {row['scene_id']}" in block
        assert f"Actual Timing: {row['start_time']} → {row['end_time']}" in block


def test_regenerated_output_is_dual_pass_and_production_ready():
    text, _ = _prompt_blocks()
    assert "Near-duplicate candidates: 0" in text
    assert "Overall Visual Diversity: PASS" in text
    assert "Overall Semantic Coherence: PASS" in text
    assert "Production Ready: YES" in text


def test_every_ai_image_has_passing_alignment_score():
    _, blocks = _prompt_blocks()
    for block in blocks:
        m = re.search(r"^- Alignment Score: (\d+)$", block, flags=re.M)
        assert m, block
        assert int(m.group(1)) >= 85
        assert "- Semantic Alignment: PASS" in block
