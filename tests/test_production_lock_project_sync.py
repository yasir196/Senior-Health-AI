from pathlib import Path

from v31_core import production_lock, sync_project_validation_context


def _config() -> dict:
    return {
        "system_version": "3.2",
        "production_lock_2_enabled": True,
        "writer_minimum_words": 1,
        "writer_required_headings": [],
        "target_runtime_range_minutes": [0, 100],
        "narration_words_per_minute": 145,
        "host_name": "Adrian Westbrook",
        "speech_optimizer_required_for_production": True,
        "narrative_qa_output": "14_narrative_qa.md",
        "medical_gate_2_output": "15_medical_gate_2.md",
        "production_clean_report": "production_clean_report.md",
    }


def _make_project(root: Path, name: str, *, host_ok: bool) -> Path:
    project = root / name
    project.mkdir()
    host = "Adrian Westbrook Health Educator" if host_ok else "Anonymous presenter"
    (project / "06_final_script.md").write_text(
        f"# Hook\nWhat if this helps? {host}. Talk to your doctor. Subscribe and comment. Coming up later.\n",
        encoding="utf-8",
    )
    (project / "14_narrative_qa.md").write_text("Status: PASS\nHumanization: checked\n", encoding="utf-8")
    (project / "15_medical_gate_2.md").write_text("Status: PASS\n", encoding="utf-8")
    (project / "06_humanization_report.md").write_text("Status: PASS\n", encoding="utf-8")
    (project / "06a_voice_script.md").write_text("Plain narration.\n", encoding="utf-8")
    (project / "06b_voice_checklist.md").write_text("Status: PASS\n", encoding="utf-8")
    # Match the voice source hash expected by the cleaner-current check.
    import hashlib
    digest = hashlib.sha256((project / "06a_voice_script.md").read_bytes()).hexdigest()
    (project / "production_clean_report.md").write_text(
        f"Status: PASS\nSource SHA-256: `{digest}`\n", encoding="utf-8"
    )
    return project


def test_production_lock_alternates_without_stale_project_paths(tmp_path: Path):
    project_a = _make_project(tmp_path, "project-a", host_ok=True)
    project_b = _make_project(tmp_path, "project-b", host_ok=False)
    state = {}

    for selected in (project_a, project_b, project_a, project_b):
        current = sync_project_validation_context(
            state,
            context_key="production_lock_selected_project",
            selected_project=selected,
            invalidate_keys=("production_lock_rows", "production_lock_reasons"),
        )
        lock = production_lock(current, _config())
        statuses = {check.name: check.status for check in lock.checks}
        assert statuses == {"Voice Script": "PASS"}
        assert not lock.locked
        assert state["production_lock_selected_project"] == str(selected.resolve())


def test_project_change_invalidates_only_production_lock_ui_artifacts(tmp_path: Path):
    a = tmp_path / "a"; b = tmp_path / "b"; a.mkdir(); b.mkdir()
    state = {
        "production_lock_rows": ["stale"],
        "production_lock_reasons": ["stale"],
        "unrelated": "preserve",
    }
    sync_project_validation_context(
        state,
        context_key="production_lock_selected_project",
        selected_project=a,
        invalidate_keys=("production_lock_rows", "production_lock_reasons"),
    )
    state["production_lock_rows"] = ["a"]
    sync_project_validation_context(
        state,
        context_key="production_lock_selected_project",
        selected_project=b,
        invalidate_keys=("production_lock_rows", "production_lock_reasons"),
    )
    assert "production_lock_rows" not in state
    assert "production_lock_reasons" not in state
    assert state["unrelated"] == "preserve"
