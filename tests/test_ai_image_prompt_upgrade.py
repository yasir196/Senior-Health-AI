from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ultimate_template_is_packaged():
    text = (ROOT / "VIDEO_PROMPT_TEMPLATE_ULTIMATE.md").read_text(encoding="utf-8")
    assert "NARRATIVE CONTEXT SYSTEM" in text


def test_production_agent_preserves_pipeline_authority_and_naming():
    text = (ROOT / "Agents" / "Production_Agent.md").read_text(encoding="utf-8")
    assert "07_production_sheet.csv` decides which rows are `AI_IMAGE`" in text
    assert "image_001.png" in text
    assert "assignment order, not Scene ID" in text
    assert "fixed 8-second images" in text
    assert "Visual Diversity Ledger" in text
    assert "## Visual Diversity QA" in text
    assert "08_actual_timeline.csv" in text


def test_production_command_requests_new_prompt_quality_contract():
    text = (ROOT / "app.py").read_text(encoding="utf-8")
    production = text.split('"Production Package":', 1)[1].split('"SEO":', 1)[0]
    assert "VIDEO_PROMPT_TEMPLATE_ULTIMATE.md" in production
    assert "legacy 8-second/WPM/image-count/batching allocation rules" in production
    assert "Visual Diversity Ledger" in production
    assert "image_001.png" in production
