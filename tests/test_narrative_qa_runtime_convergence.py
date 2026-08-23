from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_agent_requires_midpoint_convergence_and_rebalancing():
    text = (ROOT / "Agents" / "Narrative_QA_Agent.md").read_text(encoding="utf-8")
    assert "Midpoint narration words" in text
    assert "within ±5% of the midpoint" in text
    assert "Rebalance internally" in text
    assert "Another runtime-only revision expected" in text


def test_output_template_contains_prediction_and_convergence_sections():
    text = (ROOT / "Templates" / "Writing" / "narrative_qa_output_template.md").read_text(encoding="utf-8")
    assert "### Runtime Prediction" in text
    assert "Projected narration words" in text
    assert "### Convergence Check" in text
    assert "Rebalancing completed before output" in text


def test_direct_run_prompt_blocks_overshoot_and_oscillation():
    text = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "target, maximum, and midpoint narration words" in text
    assert "Never intentionally expand toward the maximum" in text
    assert "overshoot, or oscillate" in text
