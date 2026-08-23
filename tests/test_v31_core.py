from pathlib import Path

from v31_core import (
    count_words,
    estimate_runtime_minutes,
    extract_gate_status,
    narrative_qa_ready,
    next_action,
    production_lock,
    save_uploaded_script,
    validate_final_script,
    weighted_progress,
)


def valid_script(words_per_section: int = 80) -> str:
    filler = " ".join(["healthy"] * words_per_section)
    return f"""# Hook
{filler}

# Introduction
{filler}

# Main Content
{filler}

# Conclusion
{filler}

Please talk to your doctor and subscribe for more evidence-based education.
"""


def valid_voice_script() -> str:
    filler = " ".join(["healthy"] * 320)
    return (
        "I am Adrian Westbrook, your Health Educator. "
        "Today we will walk through this clearly and carefully. "
        + filler
        + " Please talk to your doctor and subscribe for more evidence-based education.\n"
    )


def base_config() -> dict:
    return {
        "speech_optimizer_required_for_production": True,
        "writer_minimum_words": 300,
        "writer_required_headings": ["hook", "introduction", "main content", "conclusion"],
        "narration_words_per_minute": 145,
        "target_runtime_range_minutes": [23, 28],
    }


def test_gate_status_parser():
    assert extract_gate_status("Status: PASS") == "PASS"
    assert extract_gate_status("Final Verdict: PASS WITH SUGGESTIONS") == "PASS WITH SUGGESTIONS"
    assert extract_gate_status("Gate Result: FAIL") == "FAIL"
    assert extract_gate_status("Narrative notes only") == "UNKNOWN"


def test_production_lock_opens_with_voice_script_only(tmp_path: Path):
    config = base_config()
    assert production_lock(tmp_path, config).locked
    (tmp_path / "06a_voice_script.md").write_text("voice", encoding="utf-8")
    lock = production_lock(tmp_path, config)
    assert not lock.locked
    assert [check.name for check in lock.checks] == ["Voice Script"]


def test_failed_upstream_gate_does_not_block_production(tmp_path: Path):
    config = base_config()
    (tmp_path / "06a_voice_script.md").write_text("voice", encoding="utf-8")
    (tmp_path / "14_narrative_qa.md").write_text("Status: FAIL", encoding="utf-8")
    (tmp_path / "15_medical_gate_2.md").write_text("Status: FAIL", encoding="utf-8")
    assert not production_lock(tmp_path, config).locked


def test_weighted_progress_is_bounded(tmp_path: Path):
    assert weighted_progress(tmp_path, base_config()) == 0
    (tmp_path / "06_final_script.md").write_text(valid_script(), encoding="utf-8")
    (tmp_path / "14_narrative_qa.md").write_text("Status: PASS", encoding="utf-8")
    (tmp_path / "15_medical_gate_2.md").write_text("Status: PASS", encoding="utf-8")
    assert 0 < weighted_progress(tmp_path, base_config()) <= 100


def test_successful_upload_and_manual_log(tmp_path: Path):
    (tmp_path / "05_script_outline.md").write_text("outline", encoding="utf-8")
    log_dir = tmp_path / "logs"
    result = save_uploaded_script(tmp_path, "claude_script.txt", valid_script().encode(), base_config(), log_dir=log_dir)
    assert result.success
    assert (tmp_path / "06_final_script.md").exists()
    assert result.validation.valid
    assert (tmp_path / ".manual_events.jsonl").exists()
    assert (log_dir / "manual_events.jsonl").exists()
    assert "writer_workspace_upload" in (tmp_path / ".last_run.json").read_text(encoding="utf-8")


def test_missing_script_is_invalid_and_blocks_narrative_qa(tmp_path: Path):
    (tmp_path / "05_script_outline.md").write_text("outline", encoding="utf-8")
    validation = validate_final_script(tmp_path, base_config())
    ready, reasons = narrative_qa_ready(tmp_path, base_config())
    assert not validation.valid
    assert not ready
    assert any("missing" in reason.lower() for reason in reasons)


def test_invalid_extension_is_rejected_without_write(tmp_path: Path):
    result = save_uploaded_script(tmp_path, "script.pdf", b"not a script", base_config())
    assert not result.success
    assert not (tmp_path / "06_final_script.md").exists()


def test_path_traversal_filename_is_rejected(tmp_path: Path):
    result = save_uploaded_script(tmp_path, "../script.md", valid_script().encode(), base_config())
    assert not result.success
    assert not (tmp_path / "06_final_script.md").exists()


def test_overwrite_creates_backup(tmp_path: Path):
    destination = tmp_path / "06_final_script.md"
    destination.write_text(valid_script(81), encoding="utf-8")
    old = destination.read_text(encoding="utf-8")
    result = save_uploaded_script(tmp_path, "replacement.md", valid_script(90).encode(), base_config())
    assert result.success
    assert result.backup_path
    backup = Path(result.backup_path)
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == old
    assert destination.read_text(encoding="utf-8") != old


def test_word_count_and_runtime_calculation():
    text = "one two three four five"
    assert count_words(text) == 5
    assert estimate_runtime_minutes(290, 145) == 2.0
    assert estimate_runtime_minutes(text, 5) == 1.0


def test_narrative_qa_unlocks_after_valid_upload(tmp_path: Path):
    (tmp_path / "05_script_outline.md").write_text("outline", encoding="utf-8")
    assert not narrative_qa_ready(tmp_path, base_config())[0]
    save_uploaded_script(tmp_path, "script.md", valid_script().encode(), base_config())
    assert narrative_qa_ready(tmp_path, base_config())[0]


def test_dashboard_progress_and_next_action_include_writer_workspace(tmp_path: Path):
    config = base_config()
    for filename in ["01_topic_validation.md", "02_research_sheet.md", "03_titles.md", "04_thumbnail_concepts.md", "05_script_outline.md", "opus_writer_package.md"]:
        (tmp_path / filename).write_text("ready", encoding="utf-8")
    before = weighted_progress(tmp_path, config)
    assert next_action(tmp_path, config) == "Writer Workspace"
    save_uploaded_script(tmp_path, "script.txt", valid_script().encode(), config)
    after = weighted_progress(tmp_path, config)
    assert after > before
    assert next_action(tmp_path, config) == "Narrative QA"

from v31_core import (
    apply_revision_patch, clean_production_script, ensure_production_cleaner,
    get_gate_status, parse_revision_patch, production_cleaner_is_current,
    production_cleaner_prerequisites, qa_dashboard, script_quality_metrics, stage_ready,
)


def test_revision_patch_parser_and_apply_creates_backup(tmp_path: Path):
    script = valid_script(90)
    current = "Please talk to your doctor and subscribe for more evidence-based education."
    replacement = "Please talk with your healthcare professional, and subscribe for more evidence-based education."
    (tmp_path / "06_final_script.md").write_text(script, encoding="utf-8")
    (tmp_path / "14_narrative_qa.md").write_text(f"""Status: PASS WITH REVISIONS

## Revision Patch
### Revision 1
Section: Conclusion
Current Text: {current}
Replace With: {replacement}
Reason: Improve natural delivery.
Severity: MEDIUM
""", encoding="utf-8")
    items = parse_revision_patch((tmp_path / "14_narrative_qa.md").read_text())
    assert len(items) == 1
    result = apply_revision_patch(tmp_path, "14_narrative_qa.md")
    assert result.success and result.applied == 1
    assert replacement in (tmp_path / "06_final_script.md").read_text(encoding="utf-8")
    assert result.backup_path and Path(result.backup_path).exists()


def test_revision_patch_skips_unmatched_text(tmp_path: Path):
    (tmp_path / "06_final_script.md").write_text(valid_script(), encoding="utf-8")
    (tmp_path / "15_medical_gate_2.md").write_text("""Status: PASS WITH REVISIONS
### Revision 1
Section: Hook
Current Text: text that does not exist
Replace With: replacement
Reason: safety
Severity: HIGH
""", encoding="utf-8")
    result = apply_revision_patch(tmp_path, "15_medical_gate_2.md")
    assert not result.success and result.skipped == 1


def test_separate_report_content_inside_script_is_invalid(tmp_path: Path):
    (tmp_path / "06_final_script.md").write_text(valid_script() + "\n# Runtime Metrics\n25 minutes\n", encoding="utf-8")
    validation = validate_final_script(tmp_path, base_config())
    assert not validation.valid
    assert any("separate" in issue.lower() for issue in validation.issues)


def test_production_cleaner_normalizes_plain_voice_and_reports(tmp_path: Path):
    text = valid_voice_script().rstrip() + "   \n\n\n"
    final_script=tmp_path / "06_final_script.md"; final_script.write_text(valid_script().replace("# Introduction\n", "# Introduction\nI am Adrian Westbrook, your Health Educator.\n"), encoding="utf-8")
    original_final=final_script.read_text(encoding="utf-8")
    (tmp_path / "06a_voice_script.md").write_text(text, encoding="utf-8")
    result = clean_production_script(tmp_path, base_config())
    assert result.success
    cleaned = (tmp_path / "06a_voice_script.md").read_text(encoding="utf-8")
    assert cleaned.endswith("\n")
    assert "   \n" not in cleaned
    assert final_script.read_text(encoding="utf-8") == original_final
    report=(tmp_path / "production_clean_report.md").read_text(encoding="utf-8")
    assert "Status: PASS" in report
    assert "No Markdown/headings checked" in report
    assert result.backup_path and Path(result.backup_path).exists()


def test_production_cleaner_rejects_markdown_headings(tmp_path: Path):
    (tmp_path / "06_final_script.md").write_text(valid_script(), encoding="utf-8")
    (tmp_path / "06a_voice_script.md").write_text("# Hook\nPlain narration. Subscribe for more.\n", encoding="utf-8")
    result=clean_production_script(tmp_path,base_config())
    assert not result.success
    assert any("must contain plain narration with no headings" in issue for issue in result.issues)


def test_production_cleaner_rejects_voice_artifacts(tmp_path: Path):
    (tmp_path / "06_final_script.md").write_text(valid_script(), encoding="utf-8")
    (tmp_path / "06a_voice_script.md").write_text("Plain narration. [Visual Cue: walking] <break time=\"1s\"/> Subscribe for more.\n", encoding="utf-8")
    result=clean_production_script(tmp_path,base_config())
    assert not result.success
    joined=" ".join(result.issues)
    assert "Visual Cue" in joined
    assert "SSML" in joined
    assert "Bracket tag" in joined


def test_script_quality_metrics_are_calculated():
    text = """# Hook
Can you imagine this? You can start today. You can keep going.

# Introduction
We're here, and we'll explain it clearly. Don't rush.
"""
    metrics = script_quality_metrics(text, {"narration_words_per_minute": 150})
    assert metrics.average_sentence_length > 0
    assert metrics.average_paragraph_length > 0
    assert metrics.rhetorical_question_count == 1
    assert metrics.estimated_narration_wpm == 150
    assert metrics.section_runtime


def test_auto_stage_progression(tmp_path: Path):
    config = base_config()
    (tmp_path / "05_script_outline.md").write_text("outline", encoding="utf-8")
    (tmp_path / "06_final_script.md").write_text(valid_script(), encoding="utf-8")
    assert stage_ready(tmp_path, "Narrative QA", config)[0]
    assert not stage_ready(tmp_path, "Medical Gate 2", config)[0]
    (tmp_path / "14_narrative_qa.md").write_text("Status: PASS", encoding="utf-8")
    assert stage_ready(tmp_path, "Medical Gate 2", config)[0]
    (tmp_path / "15_medical_gate_2.md").write_text("Status: PASS WITH REVISIONS", encoding="utf-8")
    assert not stage_ready(tmp_path, "Speech Optimizer", config)[0]
    (tmp_path / "15_medical_gate_2.md").write_text("Status: PASS", encoding="utf-8")
    assert stage_ready(tmp_path, "Speech Optimizer", config)[0]


def test_qa_dashboard_contains_four_existing_stages(tmp_path: Path):
    config = base_config()
    (tmp_path / "14_narrative_qa.md").write_text("Status: PASS\n- One note", encoding="utf-8")
    rows = qa_dashboard(tmp_path, config)
    assert [row["Stage"] for row in rows] == ["Narrative QA", "Medical Gate 2", "Speech Optimizer", "Production Cleaner"]
    assert rows[0]["Status"] == "PASS"
    assert rows[0]["Issues"] >= 1


def test_production_lock_checks_only_voice_script(tmp_path: Path):
    lock = production_lock(tmp_path, {**base_config(), "production_lock_2_enabled": True})
    assert [check.name for check in lock.checks] == ["Voice Script"]


def numbered_script() -> str:
    sections=[]
    for number in range(1,12):
        body=("This is a clear sentence. It is useful for listeners. " * 12)
        sections.append(f"# Section {number}\n{body}")
    sections.append("Please talk to your doctor and subscribe for more evidence-based education.")
    return "\n\n".join(sections)


def test_numbered_section_schema_is_backward_compatible(tmp_path: Path):
    (tmp_path / "06_final_script.md").write_text(numbered_script(), encoding="utf-8")
    validation=validate_final_script(tmp_path,{**base_config(),"writer_minimum_words":100})
    assert validation.valid
    assert validation.missing_headings == []


def test_actionable_metrics_include_breakdown_locations_and_contractions():
    text="""# Hook
That is useful. That is clear. That is practical. That is safe.

# Main Content
It is easy. It is helpful. It is memorable. We are ready.
"""
    metrics=script_quality_metrics(text,{"narration_words_per_minute":150})
    assert set(metrics.read_aloud_breakdown) == {"Sentence Variety","Contractions","Paragraph Flow","Repeated Openings","Breathing Rhythm"}
    assert metrics.total_runtime_minutes >= 0
    assert metrics.estimated_video_duration_minutes >= metrics.total_runtime_minutes
    assert metrics.contraction_opportunity_count >= 8
    assert any(item["source"] == "It is" and item["replacement"] == "It's" for item in metrics.contraction_opportunities)
    repeated=next(item for item in metrics.repeated_opening_details if item["opening"] == "that is")
    assert repeated["level"] in {"Moderate","High"}
    assert repeated["occurrences"][0]["section"] == "Hook"
    assert repeated["occurrences"][0]["sentence"] >= 1


def test_runtime_metrics_flag_significantly_long_section():
    text="# Short\nOne short sentence.\n\n# Long\n" + ("This is a longer spoken sentence with useful context. " * 120)
    metrics=script_quality_metrics(text,{"narration_words_per_minute":150})
    assert metrics.total_runtime_minutes == estimate_runtime_minutes(count_words(text.replace("# Short","").replace("# Long","")),150)
    assert "Long" in metrics.long_sections


def test_qa_dashboard_includes_last_run_timestamp(tmp_path: Path):
    (tmp_path / "14_narrative_qa.md").write_text("Status: PASS\n- Issue",encoding="utf-8")
    row=qa_dashboard(tmp_path,base_config())[0]
    assert row["Last Run"] != "-"
    assert row["Report"] == "14_narrative_qa.md"


def test_production_lock_missing_voice_reason_is_actionable(tmp_path: Path):
    config={**base_config(),"production_lock_2_enabled":True}
    lock=production_lock(tmp_path,config)
    assert lock.locked
    assert "06a_voice_script.md" in lock.reasons[0]
    assert "missing or empty" in lock.reasons[0]


def test_gate_status_parser_accepts_markdown_and_whitespace():
    assert extract_gate_status("## **Status:**   **PASS WITH REVISIONS**  ") == "PASS WITH REVISIONS"
    assert extract_gate_status("- Final Verdict : `PASS WITH SUGGESTIONS`") == "PASS WITH SUGGESTIONS"
    assert extract_gate_status("> Gate Status - **FAIL**") == "FAIL"


def test_shared_gate_status_reads_latest_report_without_cache(tmp_path: Path):
    report = tmp_path / "14_narrative_qa.md"
    transitions = [
        ("PASS", "PASS"),
        ("PASS WITH REVISIONS", "PASS WITH REVISIONS"),
        ("FAIL", "FAIL"),
        ("PASS", "PASS"),
        ("PASS WITH REVISIONS", "PASS WITH REVISIONS"),
        ("FAIL", "FAIL"),
    ]
    for raw, expected in transitions:
        report.write_text(f"# Narrative QA\n\n**Status:** **{raw}**\n", encoding="utf-8")
        assert get_gate_status(tmp_path, "Narrative QA", base_config()).status == expected
        assert qa_dashboard(tmp_path, base_config())[0]["Status"] == expected


def test_speech_optimizer_requires_both_exact_pass_and_refreshes(tmp_path: Path):
    config = base_config()
    narrative = tmp_path / "14_narrative_qa.md"
    medical = tmp_path / "15_medical_gate_2.md"
    narrative.write_text("Status: PASS", encoding="utf-8")
    medical.write_text("Status: PASS", encoding="utf-8")
    assert stage_ready(tmp_path, "Speech Optimizer", config)[0]
    narrative.write_text("Status: PASS WITH REVISIONS", encoding="utf-8")
    assert not stage_ready(tmp_path, "Speech Optimizer", config)[0]
    narrative.write_text("Status: PASS", encoding="utf-8")
    medical.write_text("Status: FAIL", encoding="utf-8")
    assert not stage_ready(tmp_path, "Speech Optimizer", config)[0]
    medical.write_text("Status: PASS", encoding="utf-8")
    assert stage_ready(tmp_path, "Speech Optimizer", config)[0]


def test_production_lock_ignores_latest_shared_gate_status(tmp_path: Path):
    config = base_config()
    (tmp_path / "06a_voice_script.md").write_text("voice", encoding="utf-8")
    narrative = tmp_path / "14_narrative_qa.md"
    medical = tmp_path / "15_medical_gate_2.md"
    narrative.write_text("Status: FAIL", encoding="utf-8")
    medical.write_text("Status: FAIL", encoding="utf-8")
    assert not production_lock(tmp_path, config).locked


def _ready_for_cleaner(project: Path, voice_text: str | None = None) -> dict:
    config={**base_config(), "system_version":"3.2", "production_lock_2_enabled":True, "target_runtime_range_minutes":[0,100]}
    (project / "06_final_script.md").write_text(valid_script().replace("# Introduction\n", "# Introduction\nI am Adrian Westbrook, your Health Educator. What should you know next?\n"), encoding="utf-8")
    (project / "14_narrative_qa.md").write_text("Status: PASS", encoding="utf-8")
    (project / "15_medical_gate_2.md").write_text("Status: PASS", encoding="utf-8")
    if voice_text is not None:
        (project / "06a_voice_script.md").write_text(voice_text, encoding="utf-8")
    (project / "06b_voice_checklist.md").write_text("Status: PASS", encoding="utf-8")
    (project / "06_humanization_report.md").write_text("Status: PASS", encoding="utf-8")
    return config

def test_missing_cleaner_report_runs_and_unlocks(tmp_path: Path):
    config=_ready_for_cleaner(tmp_path, valid_voice_script())
    result=ensure_production_cleaner(tmp_path,config)
    assert result and result.success
    assert (tmp_path / "production_clean_report.md").exists()
    assert production_cleaner_is_current(tmp_path,config)
    assert not production_lock(tmp_path,config).locked

def test_missing_speech_output_blocks_cleaner(tmp_path: Path):
    config=_ready_for_cleaner(tmp_path, None)
    ready,reasons=production_cleaner_prerequisites(tmp_path,config)
    assert not ready
    assert ensure_production_cleaner(tmp_path,config) is None
    assert any("06a_voice_script.md" in reason for reason in reasons)
    assert not (tmp_path / "production_clean_report.md").exists()

def test_cleaner_failure_is_reported_but_does_not_block_production_entry(tmp_path: Path):
    config=_ready_for_cleaner(tmp_path, "# Hook\nNarration with a forbidden heading. Subscribe for more.\n")
    result=ensure_production_cleaner(tmp_path,config)
    assert result and not result.success
    assert "Status: FAIL" in (tmp_path / "production_clean_report.md").read_text(encoding="utf-8")
    assert not production_lock(tmp_path,config).locked

def test_current_passed_cleaner_does_not_rerun(tmp_path: Path):
    config=_ready_for_cleaner(tmp_path, valid_voice_script())
    first=ensure_production_cleaner(tmp_path,config); assert first and first.success
    report=tmp_path / "production_clean_report.md"; before=report.stat().st_mtime_ns
    second=ensure_production_cleaner(tmp_path,config)
    assert second is None
    assert report.stat().st_mtime_ns == before

def test_source_change_makes_cleaner_report_stale_but_not_production_entry(tmp_path: Path):
    config=_ready_for_cleaner(tmp_path, valid_voice_script())
    first=ensure_production_cleaner(tmp_path,config); assert first and first.success
    voice=tmp_path / "06a_voice_script.md"
    voice.write_text(voice.read_text(encoding="utf-8")+"\n\nNew narration line.",encoding="utf-8")
    assert not production_cleaner_is_current(tmp_path,config)
    assert not production_lock(tmp_path,config).locked
    rerun=ensure_production_cleaner(tmp_path,config); assert rerun and rerun.success
    assert production_cleaner_is_current(tmp_path,config)


def test_validate_production_mix_requires_exact_100_percent():
    from v31_core import validate_production_mix
    ok, reason = validate_production_mix(40, 30, 10, 20)
    assert ok is True
    assert "valid" in reason.lower()
    ok, reason = validate_production_mix(40, 30, 10, 10)
    assert ok is False
    assert "90%" in reason


def test_production_outputs_reports_expected_files(tmp_path):
    from v31_core import production_outputs, PRODUCTION_OUTPUT_FILES
    project = tmp_path / "project"
    project.mkdir()
    (project / "07_production_sheet.csv").write_text("scene\n1\n", encoding="utf-8")
    result = production_outputs(project)
    assert set(result) == set(PRODUCTION_OUTPUT_FILES)
    assert result["07_production_sheet.csv"] is True
    assert result["10_image_prompts.md"] is False
    assert result["12_broll_prompts.md"] is False


def test_production_page_uses_shared_word_count_and_generation_action():
    app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    production_source = app_source.split("def render_production() -> None:", 1)[1].split("def load_production_sheet", 1)[0]
    assert "count_words(voice_script)" in production_source
    assert "word_count(" not in production_source
    assert '"Generate Production Plan"' in production_source
    assert "run_external_command(cli_template, prompt, project)" in production_source
    assert "disabled=generate_disabled" in production_source
