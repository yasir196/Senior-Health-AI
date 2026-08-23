from pathlib import Path

from semantic_coherence import audit_semantic_coherence, classify_structural_role, enforce_final_semantic_report


def block(n, script, prompt, purpose="PROBLEM", narrative="", visual_type=""):
    return f"""### IMAGE {n:03d}\n\n- Filename: image_{n:03d}.png\n- Scene ID: S{n:03d}\n- Narrative Purpose: {purpose}\n- Script Context: {script}\n- Narrative Context: {narrative}\n- Visual Type: {visual_type}\n- Final AI IMAGE PROMPT: {prompt}\n- Rewritten: YES\n"""


def test_night_context_plus_morning_light_is_detected_from_final_prompt():
    text = block(1, "At bedtime, the routine ends for the night.", "Quiet bedside scene with soft morning window light.", narrative="nighttime routine")
    audit = audit_semantic_coherence(text)
    assert any(i.category == "time_of_day" and i.image_number == 1 for i in audit.issues)


def test_morning_context_plus_evening_light_is_detected_bidirectionally():
    text = block(1, "During the morning routine...", "Person begins the day under warm evening sunset light.")
    audit = audit_semantic_coherence(text)
    assert any(i.category == "time_of_day" for i in audit.issues)


def test_host_signoff_classifies_as_structural_close_topic_agnostically():
    assert classify_structural_role("I'm Alex Morgan, and I'll see you in the next one.") == "STRUCTURAL_CLOSE"


def test_structural_close_does_not_silently_inherit_recurring_topic_terms():
    prior = "".join(block(i, "substantive explanation", "person handles copper vessel during garden exercise", narrative="topic") for i in range(1, 6))
    close = block(6, "I'm Alex Morgan, and I'll see you in the next one.", "copper vessel beside garden equipment as the lesson closes", purpose="STRUCTURAL")
    audit = audit_semantic_coherence(prior + close)
    assert any(i.category == "structural_mismatch" and i.image_number == 6 for i in audit.issues)


def test_qa_is_recalculated_from_final_prompt_and_unresolved_conflict_forces_fail(tmp_path: Path):
    p = tmp_path / "10_image_prompts.md"
    p.write_text(block(1, "bedtime tonight", "bedside composition in morning daylight") + "\n## Visual Diversity QA\n\nNear-duplicate candidates: 0\nOverall Visual Diversity: PASS\n\n## Semantic Coherence QA\n\nTime-of-day conflicts: 0\nOverall Semantic Coherence: PASS\n\nProduction Ready: YES\n", encoding="utf-8")
    audit = enforce_final_semantic_report(p)
    out = p.read_text(encoding="utf-8")
    assert not audit.passed
    assert "IMAGE 001 — time_of_day" in out
    assert "Overall Semantic Coherence: FAIL" in out
    assert "Production Ready: NO" in out


def test_visual_diversity_pass_text_is_not_modified_by_semantic_validator(tmp_path: Path):
    p = tmp_path / "10_image_prompts.md"
    p.write_text(block(1, "calm closing thought", "finished notebook on a neutral desk", purpose="STRUCTURAL") + "\n## Visual Diversity QA\n\nNear-duplicate candidates: 0\nOverall Visual Diversity: PASS\n\nProduction Ready: YES\n", encoding="utf-8")
    enforce_final_semantic_report(p)
    out = p.read_text(encoding="utf-8")
    assert "Near-duplicate candidates: 0" in out
    assert "Overall Visual Diversity: PASS" in out


def test_alignment_score_below_85_forces_fail():
    text = block(1, "one tablespoon carries about 120 calories", "older adult seated in a living-room chair checking reflux tolerance").replace("- Alignment Score: 95", "- Alignment Score: 40")
    audit = audit_semantic_coherence(text)
    assert any(i.category == "narration_alignment" and i.image_number == 1 for i in audit.issues)


def test_missing_alignment_score_forces_fail():
    text = block(1, "measure olive oil with the meal", "measured spoon of olive oil beside the plate").replace("- Alignment Score: 95\n", "")
    audit = audit_semantic_coherence(text)
    assert any(i.category == "narration_alignment" and i.image_number == 1 for i in audit.issues)
