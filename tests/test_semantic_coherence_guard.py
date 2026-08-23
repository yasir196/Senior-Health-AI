import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Agents" / "Production_Agent.md"


def agent_text():
    return AGENT.read_text(encoding="utf-8")


def test_guard_runs_after_diversity_before_finalization():
    text = agent_text()
    assert "after Visual Diversity convergence terminates and before `10_image_prompts.md` is written" in text
    assert "never weakens, bypasses, or removes the Visual Diversity Engine" in text


def test_priority_preserves_accuracy_over_diversity():
    text = agent_text()
    ordered = [
        "1. exact current Script Context",
        "2. immediate previous/following Narrative Context",
        "3. medical / evidence boundaries",
        "4. visual clarity",
        "5. human / anatomical realism",
        "6. visual diversity",
        "7. camera / composition variation",
    ]
    positions = [text.index(x) for x in ordered]
    assert positions == sorted(positions)
    assert "prefer a fully documented Intentional Repetition" in text
    assert "Alignment Score >= 85" in text
    assert "If this image were shown with the audio muted" in text


def test_topic_agnostic_semantic_dimensions_are_required():
    text = agent_text()
    for field in (
        "narration_visual_relevance", "setting_action_compatibility",
        "time_of_day_consistency", "object_location_compatibility",
        "narrative_purpose_preservation", "emotional_tone_consistency",
        "real_world_plausibility", "structural_narration_role",
        "preceding_visual_fit", "following_visual_fit",
    ):
        assert f"`{field}`" in text
    assert "Do not hardcode particular foods, rooms, symptoms, routines" in text


def test_rewrite_must_be_validated_against_context_and_neighbors():
    text = agent_text()
    for required in (
        "original Script Context", "Narrative Context", "preceding visual", "following visual",
        "Would a human editor consider this image a natural illustration of what is being said at this exact moment?",
    ):
        assert required in text
    assert "Re-derive its Core Visual Signature" in text
    assert "rerun all affected diversity calculations" in text


def test_structural_narration_does_not_force_main_topic_visual():
    text = agent_text()
    for role in ("intro", "transition", "recap", "CTA", "sign-off"):
        assert role in text
    assert "do not automatically inject the video's dominant object" in text
    assert "neutral/supportive visual strategy" in text


def test_coherence_retry_limits_are_configurable():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["semantic_coherence"]
    assert cfg["enabled"] is True
    assert cfg["max_correction_passes"] > 0
    assert cfg["max_prompt_corrections"] > 0
    text = agent_text()
    assert "semantic_coherence.max_correction_passes" in text
    assert "semantic_coherence.max_prompt_corrections" in text


def test_required_semantic_coherence_qa_metrics_present():
    text = agent_text()
    for metric in (
        "Setting/action conflicts", "Time-of-day conflicts",
        "Narration-purpose mismatches", "Structurally inappropriate visuals",
        "Rewrites corrected", "Overall Semantic Coherence",
    ):
        assert metric in text
    assert "### Unresolved Semantic Coherence Violations" in text


def test_dual_pass_is_required_for_finalization():
    text = agent_text()
    assert "Overall Visual Diversity: PASS" in text
    assert "Overall Semantic Coherence: PASS" in text
    assert "Do not write/finalize the file with only one PASS" in text
    assert "simultaneously satisfies both systems" in text


def test_coherence_correction_cannot_silently_break_diversity():
    text = agent_text()
    assert "coherence correction must never silently create a new diversity violation" in text
    assert "recalculate its Core Visual Signature/family and rerun affected Visual Diversity QA" in text


def test_architecture_invariants_remain_untouched():
    text = agent_text()
    for invariant in (
        "Production Mix", "AI-image count", "filenames", "exact timing",
        "CapCut mapping/timing", "Avatar Timing", "Narrative QA", "Medical Gates", "B-roll", "overlays",
    ):
        assert invariant in text


def test_direct_run_requires_dual_guard():
    text = (ROOT / "app.py").read_text(encoding="utf-8")
    production = text.split('"Production Package":', 1)[1].split('"SEO":', 1)[0]
    assert "Final Semantic Coherence Guard" in production
    assert "setting/action compatibility" in production
    assert "time-of-day consistency" in production
    assert "require BOTH Overall Visual Diversity: PASS and Overall Semantic Coherence: PASS" in production
    assert "recalculate affected diversity signatures/families" in production


def test_final_prompt_text_is_semantically_parsed_for_time_conflicts():
    text = agent_text()
    assert "Final-Prompt Semantic Attribute Extraction" in text
    assert "final rendered AI prompt text itself" in text
    assert "`temporal_context` vs `lighting_time_cue`" in text
    assert "night/bedtime" not in text  # implementation contract stays topic/phrase agnostic
    assert "fixed phrase blacklist" in text


def test_bedtime_context_plus_morning_light_is_classed_as_conflict_generically():
    text = agent_text()
    assert "lighting/time cues contradict its narration or setting/activity time cues" in text
    assert "increment the appropriate Semantic Coherence QA counter" in text
    assert "metadata fields look compatible" in text


def test_morning_context_plus_evening_light_is_detected_by_same_bidirectional_rule():
    text = agent_text()
    assert "Compare these attributes pairwise for contradictions" in text
    assert "`temporal_context` vs `lighting_time_cue`" in text


def test_structural_signoff_does_not_inherit_topic_imagery():
    text = agent_text()
    assert "Classify CTA, subscribe requests, host sign-offs, episode-close lines" in text
    assert "`STRUCTURAL`" in text
    assert "not inherited by default" in text
    assert "no support in the assigned closing narration" in text


def test_failed_dual_qa_marks_output_not_production_ready():
    text = agent_text()
    assert "Production Ready: YES" in text
    assert "Production Ready: NO" in text
    assert "when either QA is FAIL" in text
