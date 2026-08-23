import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Agents" / "Production_Agent.md"


def test_visual_diversity_config_is_topic_agnostic_and_configurable():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["visual_diversity"]
    assert cfg["enabled"] is True
    assert cfg["rolling_window"] > 0
    assert 0 < cfg["max_same_core_signature_similarity"] < 1
    assert 0 < cfg["max_project_family_share"] < 1
    assert cfg["max_rewrite_attempts"] > 0


def test_core_signature_contains_required_semantic_fields():
    text = AGENT.read_text(encoding="utf-8")
    for field in (
        "narrative_purpose", "primary_subject", "secondary_subject", "primary_action",
        "dominant_object", "object_relationship", "setting_category", "scene_archetype",
        "visual_metaphor", "emotional_function", "composition_family", "camera_distance",
        "camera_angle", "lighting_family",
    ):
        assert f"`{field}`" in text


def test_camera_room_and_lighting_cannot_fake_diversity():
    text = AGENT.read_text(encoding="utf-8")
    assert "Camera/location/lighting variation alone is never sufficient" in text
    assert "camera distance/angle and lighting are low-weight" in text


def test_dynamic_families_and_project_local_ledger():
    text = AGENT.read_text(encoding="utf-8")
    assert "Discover `core_visual_family` labels from the current project's Core Visual Signatures" in text
    assert "Reset this ledger at the start of every new project" in text
    assert "No cross-project diversity memory is permitted" in text


def test_intentional_continuity_requires_explicit_justification():
    text = AGENT.read_text(encoding="utf-8")
    assert "why repetition is narratively necessary" in text
    assert "what new visual information this image adds" in text
    assert "why a different visual strategy would reduce narrative accuracy" in text


def test_required_semantic_qa_metrics_are_present():
    text = AGENT.read_text(encoding="utf-8")
    for metric in (
        "Discovered core visual families", "Largest family", "Near-duplicate candidates",
        "Prompts rewritten automatically", "Longest same-family run",
        "Repeated primary-action violations", "Repeated object-relationship violations",
        "Composition repetition violations", "Intentional repetitions", "Overall Visual Diversity",
    ):
        assert metric in text


def test_production_architecture_invariants_are_explicit():
    text = AGENT.read_text(encoding="utf-8")
    assert "`07_production_sheet.csv` remains authoritative for AI-image assignments" in text
    assert "`08_actual_timeline.csv` remains authoritative for exact actual timing" in text
    assert "Production Mix remains authoritative for allocation" in text
    assert "Do not alter image count logic" in text
    assert "CapCut timings" in text


def test_direct_run_prompt_invokes_semantic_engine():
    text = (ROOT / "app.py").read_text(encoding="utf-8")
    production = text.split('"Production Package":', 1)[1].split('"SEO":', 1)[0]
    assert "Core Visual Signatures" in production
    assert "project-local visual families" in production
    assert "config-driven semantic duplicate" in production
    assert "reset the ledger per project" in production


def test_convergence_pass_limit_is_configurable():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["visual_diversity"]
    assert cfg["max_convergence_passes"] > 0
    assert cfg["max_rewrite_attempts"] > 0


def test_similarity_one_cannot_survive_silently():
    text = AGENT.read_text(encoding="utf-8")
    assert "similarity = 1.00" in text
    assert "Rewritten: NO" in text
    assert "Intentional Repetition: YES" in text
    assert "invalid final state" in text


def test_violations_trigger_iterative_rewrite_and_recalculation():
    text = AGENT.read_text(encoding="utf-8")
    assert "bounded convergence loop" in text
    assert "QA -> rewrite -> signature recalculation" in text
    assert "Re-derive the rewritten prompt's Core Visual Signature" in text
    assert "recalculate semantic QA using the new signature" in text


def test_convergence_stops_at_pass_when_possible():
    text = AGENT.read_text(encoding="utf-8")
    assert "all configurable hard thresholds pass" in text
    assert "Overall Visual Diversity: PASS" in text
    assert "Do **not** write or finalize `10_image_prompts.md` yet" in text


def test_narrative_required_repetition_must_be_documented():
    text = AGENT.read_text(encoding="utf-8")
    assert "Intentional Repetition: YES" in text
    assert "full continuity justification required by section 7.5" in text


def test_retry_limits_prevent_infinite_loop():
    text = AGENT.read_text(encoding="utf-8")
    assert "max_convergence_passes" in text
    assert "max_rewrite_attempts" in text
    assert "prevent infinite loops" in text


def test_fake_rewrites_do_not_count():
    text = AGENT.read_text(encoding="utf-8")
    assert "fake rewrite" in text
    assert "major semantic dimension" in text
    assert "human-vs-object-vs-process representation" in text


def test_hard_balance_limits_are_enforced_not_reported_only():
    text = AGENT.read_text(encoding="utf-8")
    for key in (
        "max_same_core_family_in_window", "max_project_family_share",
        "max_same_action_in_window", "max_same_object_relationship_in_window",
        "max_same_composition_in_window", "max_same_family_consecutive",
    ):
        assert key in text
    assert "Enforce, rather than merely report" in text


def test_unresolved_fail_lists_exact_prompts_and_reasons():
    text = AGENT.read_text(encoding="utf-8")
    assert "### Unresolved Diversity Violations" in text
    assert "image number, Scene ID, violated threshold(s)" in text
    assert "why no safe narratively valid alternative could be used" in text


def test_direct_run_prompt_requires_convergence_before_finalization():
    text = (ROOT / "app.py").read_text(encoding="utf-8")
    production = text.split('"Production Package":', 1)[1].split('"SEO":', 1)[0]
    assert "bounded QA -> rewrite -> signature recalculation convergence loop" in production
    assert "Do not finalize 10_image_prompts.md until diversity reaches PASS" in production
    assert "similarity of 1.00 may never remain Rewritten: NO" in production


def test_unresolved_near_duplicates_keep_fail_and_exact_ids():
    text = AGENT.read_text(encoding="utf-8")
    assert "`Near-duplicate candidates` is a hard convergence result" in text
    assert "convergence MUST continue" in text
    assert "exact image IDs/numbers" in text
    assert "Overall Visual Diversity` remains FAIL" in text


def test_convergence_continues_until_pass_or_retry_bound():
    text = AGENT.read_text(encoding="utf-8")
    assert "while passes/attempts remain" in text
    assert "When the retry limit is reached" in text
