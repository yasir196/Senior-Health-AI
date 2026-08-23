from __future__ import annotations

import csv
import json
import logging
import traceback
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from csv_safety import sanitize_csv_file
from production_sheet_contract import normalize_production_sheet, PRODUCTION_SHEET_COLUMNS, validate_scene_segmentation
from v31_core import (
    PIPELINE, WORKFLOW_STAGES, count_words, detect_codex_template,
    file_progress, get_gate_status, narrative_qa_ready, next_action, production_lock,
    run_codex, save_uploaded_script, validate_final_script, validate_project, weighted_progress,
    apply_revision_patch, clean_production_script, ensure_production_cleaner, production_cleaner_prerequisites, production_cleaner_is_current, qa_dashboard, script_quality_metrics, stage_ready, validate_production_mix, production_outputs, sync_project_prompt_state, sync_project_validation_context, resolve_title_anchor, write_anchor_claim_map,
)

from avatar_timing import (
    avatar_sync_blockers, build_actual_timeline, chunk_sequence_info, discover_avatar_chunks,
    AvatarTranscriptionError, load_production_scenes, preflight_avatar_chunks, transcribe_avatar_chunks, transcription_settings, transcript_cache_is_current,
    transcript_inventory,
)
from timeline_builder import TimelineBuildError, build_timeline_manifest
from capcut_export import CapCutExportError, export_capcut_project
from semantic_coherence import enforce_final_semantic_report
from image_generation import (
    DEFAULT_MODEL_KEY, build_images_zip, enhance_prompt, generate_batch, load_manifest,
    load_production_image_assignments, model_profiles_from_config, reconcile_manifest,
    select_failed_or_missing, select_missing, select_stale,
)
from opus_image_prompt_import import load_production_ai_image_slots, validate_import, write_image_prompts
from text_overlay import ARTIFACT_NAME, parse_opus_csv, validate_rows, write_artifact

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
PROJECTS_DIR = ROOT / "Projects"
ANALYTICS_DIR = ROOT / "Analytics"
RUN_LOG_DIR = ROOT / "RunLogs"

EDITABLE_SUFFIXES = {".md", ".txt", ".json"}
VIEWABLE_SUFFIXES = {".md", ".txt", ".csv", ".json"}


@dataclass
class ProjectStatus:
    name: str
    path: Path
    present: int
    total: int
    missing: list[str]

    @property
    def percent(self) -> int:
        return round((self.present / self.total) * 100) if self.total else 0


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig")
    except (FileNotFoundError, OSError):
        return ""


def validate_production_sheet_against_voice(project: Path) -> tuple[bool, list[str]]:
    """Validate ONLY narration provenance/order against 06a_voice_script.md.

    Scene-size/timing QA is intentionally separate. Avatar Timing must not report a
    stale-script mismatch merely because a scene is short/long or has provisional
    timing that the production planner should improve.
    """
    voice_path = project / "06a_voice_script.md"
    sheet_path = project / "07_production_sheet.csv"
    if not voice_path.is_file() or not sheet_path.is_file():
        return False, ["06a_voice_script.md and 07_production_sheet.csv are required for source validation."]
    voice = safe_read_text(voice_path)
    normalize = lambda value: re.sub(r"\s+", " ", value).strip()
    voice_norm = normalize(voice)
    cursor = 0
    issues: list[str] = []
    with sheet_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return False, ["07_production_sheet.csv has no production scenes."]
    for index, row in enumerate(rows, 1):
        scene_id = str(row.get("scene_id") or row.get("Scene ID") or f"S{index:03d}").strip()
        excerpt = normalize(str(row.get("script_excerpt") or row.get("Script Text") or row.get("narration") or ""))
        if not excerpt:
            issues.append(f"{scene_id}: script_excerpt is empty.")
            continue
        pos = voice_norm.find(excerpt, cursor)
        if pos < 0:
            anywhere = voice_norm.find(excerpt)
            if anywhere >= 0:
                issues.append(f"{scene_id}: script_excerpt is out of source order.")
            else:
                issues.append(f"{scene_id}: script_excerpt is not an exact excerpt of current 06a_voice_script.md.")
        else:
            cursor = pos + len(excerpt)
    return not issues, issues


def production_sheet_segmentation_issues(project: Path) -> list[str]:
    """Return semantic scene/timing QA issues without conflating them with source provenance."""
    sheet_path = project / "07_production_sheet.csv"
    if not sheet_path.is_file():
        return ["07_production_sheet.csv is missing."]
    try:
        with sheet_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        return [f"Could not read 07_production_sheet.csv: {exc}"]
    return validate_scene_segmentation(rows)

def clear_stale_production_outputs(project: Path) -> list[str]:
    """Remove only regenerated Production-package outputs before a fresh run."""
    removed: list[str] = []
    for name in ("07_production_sheet.csv", "10_image_prompts.md", "12_broll_prompts.md"):
        path = project / name
        if path.is_file():
            try:
                path.unlink()
                removed.append(name)
            except OSError as exc:
                raise RuntimeError(f"Close {name} before regenerating Production: {exc}") from exc
    return removed


def safe_write_text(path: Path, text: str) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return True
    except OSError as exc:
        st.error(f"Could not save {path.name}: {exc}")
        return False


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(safe_read_text(CONFIG_PATH))
    except json.JSONDecodeError:
        return {}


def save_config(config: dict[str, Any]) -> None:
    safe_write_text(CONFIG_PATH, json.dumps(config, indent=2, ensure_ascii=False) + "\n")


def slugify_topic(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower().strip())
    return re.sub(r"-+", "-", slug).strip("-") or "untitled-project"


def project_dirs() -> list[Path]:
    PROJECTS_DIR.mkdir(exist_ok=True)
    return sorted((p for p in PROJECTS_DIR.iterdir() if p.is_dir()), key=lambda p: p.name.lower())


def get_project_status(project: Path) -> ProjectStatus:
    missing = [file_name for _, file_name in PIPELINE if not (project / file_name).exists()]
    return ProjectStatus(project.name, project, len(PIPELINE) - len(missing), len(PIPELINE), missing)


def project_selector(key: str) -> Path | None:
    projects = project_dirs()
    if not projects:
        st.info("No projects found. Create one from New Project.")
        return None
    name = st.selectbox("Project", [p.name for p in projects], key=f"project_{key}")
    return PROJECTS_DIR / name


def command_for_stage(project: Path, stage: str, anchor_outlier_pattern: str | None = None) -> str:
    ref = f"Projects/{project.name}/"
    commands = {
        "Topic Validation": f"Run Stage 1 only for {ref}. Read project.json.anchor_title first and treat that exact user-supplied Anchor / Outlier Title as the immutable winning title. Validate its demand/opportunity and promise without generating, rewriting, repairing, ranking, or replacing any title. Treat 01a_anchor_claim_map.json as the authoritative packaging hypothesis when present. If the exact title promise is unsupported, report the conflict instead of silently changing the title. Create only 01_topic_validation.md; preserve project.json and 01a_anchor_claim_map.json unchanged. Stop after validation.",
        "Research + Medical Gate 1": f"For {ref}, read project.json.anchor_title as the immutable winning title, then use 01a_anchor_claim_map.json plus 01_topic_validation.md. Research must neutrally test/falsify the exact title promise and hypothesis_claim rather than trying to prove it. Run Research_Agent and Medical_Agent Gate 1. Create 02_research_sheet.md, 13_fact_check_log.md, and for anchor-first projects 13a_title_repair_blueprint.json bound to the exact anchor_title. The blueprint must identify unsafe_span, reason, supported_claim_boundary/replacement lane, and frozen_architecture. Stop before titles.",
        "Thumbnail": f"For {ref}, run Thumbnail_Agent only using approved upstream files. Use project.json.anchor_title EXACTLY as the winning title; do not generate, rank, rewrite, repair, or replace the title. Create only 04_thumbnail_concepts.md and 11_thumbnail_prompt.md.",
        "Script Outline": f"For {ref}, run Script_Agent in outline_to_script mode. Use project.json.anchor_title EXACTLY as the immutable winning title and align the complete outline to its promise; do not generate or substitute another title. Create only 05_script_outline.md. Do not create 06_final_script.md.",
        "Prepare Opus Package": f"For {ref}, prepare a fresh per-project opus_writer_package.md from the current writing templates and 05_script_outline.md. Create or update only opus_writer_package.md.",
        "Writer Workspace": f"Manual stage for {ref}. Download opus_writer_package.md, write the full script in Claude, then upload the result through Writer Workspace as 06_final_script.md. Direct Codex Run is intentionally disabled for this manual stage.",
        "Narrative QA": f"For {ref}, run Narrative_QA_Agent using 05_script_outline.md, 06_final_script.md, config.json, and the Narrative QA templates. Count spoken narration only, excluding headings, Markdown, visual cues, scene labels, and production notes. Read target_runtime_minutes, target_runtime_range_minutes, and narration_words_per_minute from config.json. Review storytelling, pacing, repetition, transitions, hook payoff, tone, CTA placement, and retention. Create 14_narrative_qa.md with Status: PASS / PASS WITH REVISIONS / FAIL. If runtime is the only blocker, calculate minimum, target, maximum, and midpoint narration words; include Runtime Analysis, a Runtime Prediction table, and a Convergence Check before the Revision Patch. Size one coordinated patch toward the midpoint (normally within ±5%), simulate the projected runtime, and rebalance internally until it is inside the configured range with no further runtime-only revision expected. Never intentionally expand toward the maximum, compress toward the minimum, overshoot, or oscillate. Include estimated net word change in each runtime-driven revision Reason. Use repeated fields: Section:, Current Text:, Replace With:, Reason:, Severity:. Do not directly rewrite 06_final_script.md.",
        "Medical Gate 2": f"For {ref}, run Medical_Agent Gate 2 after Narrative QA PASS or PASS WITH REVISIONS. Compare every medical statement in 06_final_script.md against 02_research_sheet.md and 13_fact_check_log.md. Create 15_medical_gate_2.md with Status: PASS / PASS WITH REVISIONS / FAIL. When edits are required, include a structured Revision Patch using Section:, Current Text:, Replace With:, Reason:, Severity:. Update 13_fact_check_log.md only when necessary. Do not directly rewrite the script or run production.",
        "Speech Optimizer": f"For {ref}, run the Speech Optimizer directly from 06_final_script.md. Do NOT check or require Narrative QA, Medical Gate 2, Production Lock, prior workflow completion, or any other upstream gate/report. Treat 06_final_script.md as the user-approved canonical input. Use Templates/Voice/ only for speech/delivery optimization. Create only 06a_voice_script.md and 06b_voice_checklist.md. Do not modify 06_final_script.md.",
        "Production Package": f"For {ref}, 06a_voice_script.md is the ONLY authoritative source for narration and scene text. Read that file fresh from disk before planning scenes. Do NOT read, reuse, infer narration from, or copy scene text from 05_script_outline.md, 06_final_script.md, 06_final_script_locked.md, any prior 07_production_sheet.csv, 08_actual_timeline.csv, old image/B-roll prompts, run logs, caches, or any other project editorial artifact. Start Production without checking any prior editorial workflow stage, gate, checklist, title, research, outline, final-script, or production-cleaner status. Preserve the supplied narration exactly: every 07_production_sheet.csv script_excerpt must be an exact contiguous excerpt from the current 06a_voice_script.md and scene excerpts must follow source order without invented/paraphrased script lines. Respect production_settings.json. Use VIDEO_PROMPT_TEMPLATE_ULTIMATE.md only as the narrative-context/prompt-quality framework; ignore its legacy 8-second/WPM/image-count/batching allocation rules. The NEW 07_production_sheet.csv created in this run becomes authoritative for AI_IMAGE slots and assignment order. Preserve image_001.png assignment-order naming. Run the system-level semantic Visual Diversity Engine with a project-local Visual Diversity Ledger: derive Core Visual Signatures, discover project-local visual families, and enforce config-driven semantic duplicate/rolling/family-balance thresholds through the bounded QA -> rewrite -> signature recalculation convergence loop. Do not finalize 10_image_prompts.md until diversity reaches PASS or a justified unresolved FAIL is documented. A similarity of 1.00 may never remain Rewritten: NO without explicit Intentional Repetition: YES plus reason. Rewrite core concepts rather than camera/location variants, reset the ledger per project, and emit the full semantic Visual Diversity QA. After diversity convergence, run the Final Semantic Coherence Guard against original Script Context, Narrative Context, preceding visual, following visual, AND the final rendered prompt text itself; infer normalized temporal/lighting with explicit time-of-day consistency, setting/action compatibility, object/location, scene-purpose/structural-role, and emotional-tone attributes and reject contradictions even when metadata appears compatible. Explicitly detect final-prompt temporal contradictions such as night/bedtime context paired with morning/daybreak lighting, and the inverse, by semantic compatibility rather than a fixed phrase blacklist. Reject incoherent diversity rewrites, correct them within configured semantic_coherence retry bounds, recalculate affected diversity signatures/families after every coherence correction, and require BOTH Overall Visual Diversity: PASS and Overall Semantic Coherence: PASS before marking 10_image_prompts.md production-ready. Continue diversity convergence while unjustified near-duplicate candidates remain above configured limits; if retry bounds are exhausted, keep FAIL, enumerate exact unresolved image IDs, and emit Production Ready: NO rather than silently treating the diagnostic file as ready. Classify discourse role before prompt generation: host sign-off/episode-close terminal narration is STRUCTURAL_CLOSE; other CTA/subscribe/transition narration may be STRUCTURAL when appropriate. STRUCTURAL_CLOSE must not inherit recurring topic imagery unless the exact closing narration requires it. After all rewrites, run the deterministic final-output semantic verifier over final prompt text; any detected conflict overrides a stale PASS and forces exact-image reporting plus Production Ready: NO. For every AI_IMAGE candidate, treat exact current Script Context as primary authority, immediate previous/following Narrative Context second, then visual clarity, human realism, diversity, and camera/composition variation. Before accepting the final rendered prompt, apply the muted-audio semantic test: if shown without audio, would its main subject/action reasonably illustrate the narration being spoken? Emit Alignment Score: 0-100 for every image and require >=85. Below 85, rewrite the visual concept from Script Context itself; camera/style-only rewrites do not count. Never solve repetition by substituting an unrelated archetype; allow repeated objects when the narration genuinely requires them. Prefer documented intentional repetition over a less relevant visual. SEMANTIC SCENE SPLIT IS A HARD GATE: segment 06a_voice_script.md by coherent visual/narrative idea BEFORE assigning the production mix. Do not target a fixed scene count. Do not create/split/merge rows to satisfy 40/30/20/10 or any other mix. Normal scenes are roughly 8-28 spoken words; merge orphan fragments under 4 words with an adjacent beat unless notes explicitly marks INTENTIONAL_EMPHASIS; split multi-idea excerpts above roughly 34 words. A phrase such as `Just five.` must never receive a padded 6-second standalone slot by default. Provisional duration must come from narration length/natural speech, and start_time/end_time must be elapsed M:SS (e.g. 26:35), never 26:35:00. After semantic scene boundaries are frozen, apply production_settings.json only as an approximate asset-type distribution over those scenes. HARD CSV CONTRACT: 07_production_sheet.csv MUST use the existing canonical 32-column header exactly and in order: scene_id,start_time,end_time,duration_sec,scene_purpose,script_excerpt,visual_mode,avatar_required,avatar_style,background_style,image_prompt_id,broll_prompt_id,narrative_context,visual_intent,filmable,asset_decision_reason,asset_search_query,alternative_search_query_1,alternative_search_query_2,ai_image_prompt,overlay_instruction,recommended_asset_type,recommended_shot,manual_search_notes,avoid_results,asset_source,selected_asset_path,asset_status,motion,transition,on_screen_text,notes. Populate the rich production data for every row; never emit compact slot_id/slot_type/asset_type schemas. recommended_asset_type must use STOCK_VIDEO/STOCK_IMAGE/AI_IMAGE/AVATAR/OVERLAY/SPLIT_SCREEN/NO_ASSET_NEEDED. AI_IMAGE rows require sequential IMG001.. IDs and non-empty ai_image_prompt; stock rows require sequential BR001.. IDs and concrete queries. Create only 07_production_sheet.csv, 10_image_prompts.md, and 12_broll_prompts.md. AI prompts only for AI_IMAGE scenes.",
        "SEO": f"For {ref}, run SEO_Agent only after the approved script and final 08_actual_timeline.csv exist. Use project.json.anchor_title EXACTLY as the final/winning YouTube title; do not optimize, rewrite, rank, or replace it. Create or update only 08_youtube_metadata.md. For ## 5. Chapters / Timestamps, emit semantic chapter labels with S### scene anchors only; deterministic application code replaces them with Actual Audio Start timestamps from 08_actual_timeline.csv.",
        "Final QA + Summary": f"For {ref}, run Final QA only. Check all required outputs, narrative QA, Medical Gate 2, host identity, metadata, and production files. Create or update only 09_qa_checklist.md and 16_project_summary.md. Do not silently rewrite approved content.",
    }
    return commands[stage]




def detect_codex_command() -> str:
    return detect_codex_template(load_config())


def _artifact_signature(path: Path) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size

def run_external_command(command_template: str, prompt: str, project: Path, title_anchor_outlier_pattern: str | None = None, manual_titles: list[str] | None = None):
    # Title generation/judging has been removed. Every active stage reads the immutable
    # user-supplied winning title from project.json.anchor_title.
    result = run_codex(command_template, prompt, project, ROOT, RUN_LOG_DIR)
    if result.returncode == 0 and "run SEO_Agent" in prompt:
        from seo_chapters import SEOChapterError, finalize_project_seo
        try:
            diagnostics = finalize_project_seo(project)
            if diagnostics:
                result.output = (result.output + "\n\nSEO chapter finalizer:\n" + "\n".join(diagnostics))[-20000:]
        except SEOChapterError as exc:
            result.returncode = 2
            result.output = (result.output + f"\n\nSEO chapter finalization: FAIL\n{exc}")[-20000:]
    return result

def inject_css() -> None:
    st.markdown("""
    <style>
    .block-container {padding-top: 1.2rem; padding-bottom: 3rem;}
    div[data-testid="stMetric"] {border:1px solid rgba(120,120,120,.22); border-radius:14px; padding:12px;}
    .stage-card {border:1px solid rgba(120,120,120,.22); border-radius:14px; padding:12px 14px; margin-bottom:8px;}
    .ok {color:#18a558;font-weight:700}.wait {color:#cc8a00;font-weight:700}
    </style>
    """, unsafe_allow_html=True)


def render_dashboard() -> None:
    st.subheader("V3.3 Production Dashboard")
    config = load_config()
    projects = project_dirs()
    if not projects:
        st.info("No projects yet.")
        return
    rows = []
    for project in projects:
        present, total, files_pct = file_progress(project)
        lock = production_lock(project, config)
        rows.append({
            "Project": project.name, "Progress": weighted_progress(project, config),
            "Files": f"{present}/{total}", "Next Action": next_action(project, config),
            "Production": "LOCKED" if lock.locked else "READY",
        })
    df = pd.DataFrame(rows)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Projects", len(df))
    c2.metric("Average progress", f"{round(df['Progress'].mean())}%")
    c3.metric("Production ready", int((df["Production"] == "READY").sum()))
    c4.metric("Locked", int((df["Production"] == "LOCKED").sum()))
    st.dataframe(df, hide_index=True, width="stretch", column_config={"Progress": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%")})

    selected = project_selector("dashboard")
    if selected:
        pct = weighted_progress(selected, config)
        st.progress(pct / 100, text=f"Weighted workflow progress: {pct}%")
        lock = production_lock(selected, config)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Writer Workspace", "VALID" if validate_final_script(selected, config).valid else "BLOCKED")
        c2.metric("Narrative QA", get_gate_status(selected, "Narrative QA", config).status)
        c3.metric("Medical Gate 2", get_gate_status(selected, "Medical Gate 2", config).status)
        c4.metric("Production Lock", "LOCKED" if lock.locked else "OPEN")
        if lock.locked:
            st.error("Production is locked: " + " ".join(lock.reasons))
        st.markdown("### Workflow")
        for stage, filename in PIPELINE:
            exists = (selected / filename).exists()
            label, css = ("READY", "ok") if exists else ("PENDING", "wait")
            extra = ""
            if filename in {config.get("narrative_qa_output", "14_narrative_qa.md"), config.get("medical_gate_2_output", "15_medical_gate_2.md")} and exists:
                extra = f" · {get_gate_status(selected, stage, config, filename=filename).status}"
            st.markdown(f'<div class="stage-card"><span class="{css}">{label}</span> &nbsp; <b>{stage}</b>{extra}<br><small>{filename}</small></div>', unsafe_allow_html=True)


def render_new_project() -> None:
    st.subheader("New Project")
    topic = st.text_input("Anchor / Outlier Title", help="Enter the exact final video title. This user-supplied title is immutable and becomes the winning title/source of truth for validation, research, thumbnail, script, production, SEO, and QA. No title generation stage will run.")
    slug = slugify_topic(topic)
    st.caption(f"Folder: Projects/{slug}")
    if st.button("Create Project", type="primary", disabled=not topic.strip()):
        path = PROJECTS_DIR / slug; path.mkdir(parents=True, exist_ok=True)
        anchor = topic.strip()
        safe_write_text(path / "project.json", json.dumps({"topic": anchor, "anchor_title": anchor, "created_at": datetime.now().isoformat(timespec="seconds"), "version": "3.1"}, indent=2) + "\n")
        write_anchor_claim_map(path, anchor)
        defaults = load_config().get("production_defaults", {"avatar": 40, "ai_images": 30, "stock": 10, "overlays": 20})
        payload = {**defaults, "image_duration_seconds": 10, "image_platform": "Genspark Web"}
        safe_write_text(path / "production_settings.json", json.dumps(payload, indent=2) + "\n")
        st.success(f"Created {path.name}")
        st.code(command_for_stage(path, "Topic Validation"), language="text")


def render_workflow() -> None:
    st.subheader("V3.3 Workflow Control")
    project = project_selector("workflow")
    if not project:
        return
    config = load_config()
    cli_template = detect_codex_command()
    direct_enabled = bool(config.get("direct_run_enabled", True)) and bool(cli_template)
    stored_anchor = resolve_title_anchor(project)
    if stored_anchor:
        claim_map_path = project / "01a_anchor_claim_map.json"
        st.markdown("### Anchor-First Preflight")
        st.caption(f"Authoritative Winning Title: {stored_anchor}")
        st.caption(f"Claim Map: {'READY' if claim_map_path.is_file() else 'MISSING'} · 01a_anchor_claim_map.json")
    stage = st.selectbox("Stage", WORKFLOW_STAGES)
    anchor_outlier_pattern = None
    resolved_title_anchor = resolve_title_anchor(project)
    default_prompt = command_for_stage(project, stage)
    anchor_context_marker = resolved_title_anchor or ""
    prompt_context = f"{project.name}:{stage}:{anchor_context_marker}"
    prompt = sync_project_prompt_state(
        st.session_state,
        prompt_key="workflow_agent_prompt",
        context_key="workflow_agent_prompt_context",
        context_value=prompt_context,
        default_prompt=default_prompt,
    )
    lock = production_lock(project, config)
    stage_is_ready, stage_reasons = stage_ready(project, stage, config)
    stage_blocked = not stage_is_ready
    if stage == "Production Package" and stage_blocked:
        st.error("Production Lock is active. " + " ".join(lock.reasons))
    elif stage_blocked:
        st.error(f"{stage} is blocked. " + " ".join(stage_reasons))
    elif stage == "Writer Workspace":
        st.info("Writer Workspace is a manual Claude handoff stage. Use the dedicated page to download the package and upload the final script.")
    prompt = st.text_area("Agent instruction", height=230, key="workflow_agent_prompt")
    c1, c2, c3 = st.columns(3)
    c1.download_button("Download Instruction", prompt, file_name=f"{project.name}_{slugify_topic(stage)}.txt")
    run_clicked = c2.button(
        "Direct Codex Run",
        type="primary",
        disabled=not direct_enabled or stage_blocked or stage == "Writer Workspace",
    )
    if c3.button("Validate Project"):
        issues = validate_project(project, config)
        st.success("Project structure is valid.") if not issues else st.warning("\n".join(issues))
    if run_clicked:
        cleaner_ok = True
        if stage == "Production Package":
            with st.spinner("Running automatic Production Cleaner preflight..."):
                clean = clean_production_script(project, config, log_dir=RUN_LOG_DIR)
            cleaner_ok = clean.success
            if clean.success:
                st.success("Production Cleaner preflight passed.")
            else:
                st.error("Production Cleaner preflight failed. Production Package was not started.")
                for issue in clean.issues: st.write(f"- {issue}")
        if cleaner_ok:
            with st.spinner(f"Running {stage}..."):
                result = run_external_command(cli_template, prompt, project, None, None)
            if result.returncode == 0:
                if stage == "Production Package":
                    sanitize_csv_file(
                        project / "07_production_sheet.csv",
                        required_text_columns=("script_excerpt", "Script Text", "narration"),
                    )
                    prompt_output = project / "10_image_prompts.md"
                    if prompt_output.is_file():
                        semantic_audit = enforce_final_semantic_report(prompt_output)
                        if semantic_audit.passed:
                            st.success(f"{stage} completed. Log: {Path(result.log_path).name}")
                        else:
                            ids = ", ".join(f"IMAGE {x.image_number:03d}" for x in semantic_audit.issues)
                            st.error(f"{stage} generated diagnostic output but Semantic Coherence verification failed ({ids}). 10_image_prompts.md is NOT PRODUCTION READY.")
                    else:
                        st.success(f"{stage} completed. Log: {Path(result.log_path).name}")
                else:
                    st.success(f"{stage} completed. Log: {Path(result.log_path).name}")
            else:
                st.error(f"{stage} exited with code {result.returncode}.")
            st.code(result.output or "No output", language="text")
    if not direct_enabled:
        st.info("Direct Codex Run is disabled or Codex CLI is unavailable. Configure it in Config.")
    last_run = project / ".last_run.json"
    if last_run.exists():
        data = json.loads(safe_read_text(last_run) or "{}")
        st.caption(f"Last run: {data.get('finished_at', '-')} · Exit code {data.get('returncode', '-')}")


def render_writer_workspace() -> None:
    st.subheader("Writer Workspace")
    st.caption("Manual Claude writing stage between Prepare Opus Package and Narrative QA.")
    project = project_selector("writer_workspace")
    if not project:
        return
    config = load_config()
    package_path = project / "opus_writer_package.md"
    package_ready = package_path.is_file() and package_path.stat().st_size > 0
    validation = validate_final_script(project, config)

    c1, c2, c3 = st.columns(3)
    c1.metric("Opus Package", "READY" if package_ready else "MISSING")
    c2.metric("Final Script", "VALID" if validation.valid else ("INVALID" if validation.exists else "MISSING"))
    c3.metric("Narrative QA", "UNLOCKED" if validation.valid else "BLOCKED")

    if package_ready:
        st.download_button("Download Opus Package", package_path.read_bytes(), file_name=f"{project.name}_opus_writer_package.md", mime="text/markdown")
    else:
        st.warning("Prepare Opus Package must be completed first. Expected opus_writer_package.md.")

    st.markdown("### Manual instructions for Claude")
    st.info("1. Download the Opus package. 2. Upload/paste it into Claude. 3. Ask Claude to write the complete script while preserving the package rules and Markdown headings. 4. Export the result as .md or .txt. 5. Upload it below; the app will save it safely as 06_final_script.md.")

    target = f"Target: {validation.target_words_min:,}–{validation.target_words_max:,} words · {validation.target_runtime_min:g}–{validation.target_runtime_max:g} minutes at {int(config.get('narration_words_per_minute', 145))} WPM."
    st.caption(target)
    uploaded = st.file_uploader("Upload completed script", type=["md", "txt"], accept_multiple_files=False, key=f"writer_upload_{project.name}")
    existing = (project / "06_final_script.md").exists()
    if existing:
        st.warning("An existing 06_final_script.md will be backed up automatically before replacement.")
    confirm = st.checkbox("I confirm replacement of the existing script", value=not existing, disabled=not existing, key=f"writer_confirm_{project.name}")
    if st.button("Save as 06_final_script.md", type="primary", disabled=uploaded is None or (existing and not confirm)):
        result = save_uploaded_script(project, uploaded.name, uploaded.getvalue(), config, create_backup=True, log_dir=RUN_LOG_DIR)
        if result.success:
            st.success(result.message)
        else:
            st.error(result.message)
        if result.backup_path:
            st.info(f"Backup created: {Path(result.backup_path).relative_to(project)}")
        validation = result.validation

    validation = validate_final_script(project, config)
    st.markdown("### Script validation")
    m1, m2, m3 = st.columns(3)
    m1.metric("Word count", f"{validation.word_count:,}")
    m2.metric("Estimated runtime", f"{validation.runtime_minutes:g} min")
    comparison = "IN RANGE" if validation.target_words_min <= validation.word_count <= validation.target_words_max else "OUTSIDE TARGET"
    m3.metric("Target comparison", comparison)
    if validation.issues:
        for issue in validation.issues:
            st.error(issue)
    elif validation.valid:
        st.success("Required headings and basic content checks passed. Narrative QA is unlocked.")
    if validation.exists:
        st.markdown("### Script Quality Metrics")
        metrics = script_quality_metrics(safe_read_text(project / "06_final_script.md"), config)
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Avg sentence", f"{metrics.average_sentence_length:g} words", help=f"Target: {metrics.target_ranges['Average sentence length']}")
        q2.metric("Avg paragraph", f"{metrics.average_paragraph_length:g} words", help=f"Target: {metrics.target_ranges['Average paragraph length']}")
        q3.metric("Contractions", f"{metrics.contractions_percent:g}%", help=f"Target: {metrics.target_ranges['Contractions']}")
        q4.metric("Read-aloud score", f"{metrics.read_aloud_score:g}/100", help=f"Target: {metrics.target_ranges['Read-aloud score']}")
        q5, q6, q7, q8 = st.columns(4)
        q5.metric("Total runtime", f"{metrics.total_runtime_minutes:g} min")
        q6.metric("Estimated video duration", f"{metrics.estimated_video_duration_minutes:g} min")
        q7.metric("ElevenLabs pauses", metrics.estimated_elevenlabs_pauses, help=f"Target: {metrics.target_ranges['Breathing rhythm']}")
        q8.metric("Reading ease", metrics.reading_difficulty, help=f"Target: {metrics.target_ranges['Reading ease']}")

        st.markdown("#### Read-aloud Score Breakdown")
        breakdown_rows=[{"Component": name, "Score": score, "Target": "75–100"} for name, score in metrics.read_aloud_breakdown.items()]
        st.dataframe(pd.DataFrame(breakdown_rows), hide_index=True, width="stretch")

        st.markdown("#### Contraction Analysis")
        st.caption(f"{metrics.contraction_opportunity_count} possible conversational contraction opportunities found. Suggestions only; the script is not modified.")
        if metrics.contraction_opportunities:
            st.dataframe(pd.DataFrame([{"Current": item['source'], "Suggestion": item['replacement'], "Opportunities": item['count']} for item in metrics.contraction_opportunities]), hide_index=True, width="stretch")
        else:
            st.success("No common uncontracted phrases were detected.")

        st.markdown("#### Repeated Sentence Opening Inspector")
        if metrics.repeated_opening_details:
            badge_colors={"Good":"#1f9d55","Moderate":"#d69e2e","High":"#d64545"}
            for item in metrics.repeated_opening_details:
                color=badge_colors[item['level']]
                title=f"{item['opening']} ({item['count']})"
                st.markdown(f"<span style='background:{color};color:white;padding:3px 9px;border-radius:12px;font-weight:600'>{item['level']}</span> &nbsp; **{title}**", unsafe_allow_html=True)
                with st.expander(f"Show {item['count']} locations", expanded=False):
                    st.dataframe(pd.DataFrame([{"Section": occurrence['section'], "Sentence": occurrence['sentence'], "Sentence in section": occurrence['section_sentence']} for occurrence in item['occurrences']]), hide_index=True, width="stretch")
        else:
            st.success("Good: no sentence opening appears three or more times.")

        st.markdown("#### Runtime by Section")
        if metrics.section_runtime:
            runtime_rows=[]
            for name,value in metrics.section_runtime.items():
                runtime_rows.append({"Section":name,"Runtime (min)":value,"Comparison":"SIGNIFICANTLY LONGER" if name in metrics.long_sections else "Normal"})
            st.dataframe(pd.DataFrame(runtime_rows), hide_index=True, width="stretch")
            if metrics.long_sections:
                st.warning("Longer than average: " + ", ".join(metrics.long_sections))
        r1,r2=st.columns(2)
        r1.metric("Rhetorical questions", metrics.rhetorical_question_count)
        r2.metric("Narration WPM", metrics.estimated_narration_wpm)
        st.markdown("### Uploaded script preview")
        st.text_area("06_final_script.md", validation.preview, height=520, disabled=True, key=f"writer_preview_{project.name}")


def render_narrative_qa() -> None:
    st.subheader("Narrative QA Agent")
    if st.session_state.get("gate_refresh_notice"):
        st.success(st.session_state.pop("gate_refresh_notice"))
    st.caption("Checks storytelling, pacing, repetition, transitions, hook payoff, tone, CTA placement, and retention. Medical claims are checked separately in Medical Gate 2.")
    project = project_selector("narrative_qa")
    if not project:
        return

    outline_ready = (project / "05_script_outline.md").exists()
    validation = validate_final_script(project, load_config())
    script_ready = validation.valid
    narrative_gate = get_gate_status(project, "Narrative QA", load_config())
    output_ready = narrative_gate.exists

    c1, c2, c3 = st.columns(3)
    c1.metric("Script Outline", "READY" if outline_ready else "MISSING")
    c2.metric("Writer Workspace", "VALID" if script_ready else "BLOCKED")
    c3.metric("Narrative QA", narrative_gate.status)

    can_start, blocked_reasons = narrative_qa_ready(project, load_config())
    if not can_start:
        st.warning("Narrative QA cannot run yet: " + " ".join(blocked_reasons))

    default_prompt = command_for_stage(project, "Narrative QA")
    reset_prompt = st.button(
        "Reset Narrative Prompt",
        key=f"reset_narrative_prompt_{project.name}",
        help="Restore the default Narrative QA instruction for the currently selected project.",
    )
    prompt = sync_project_prompt_state(
        st.session_state,
        prompt_key="narrative_qa_prompt",
        context_key="narrative_prompt_project",
        context_value=project.name,
        default_prompt=default_prompt,
        force_reset=reset_prompt,
    )
    prompt = st.text_area("Narrative QA instruction", height=220, key="narrative_qa_prompt")

    cli_template = detect_codex_command()
    can_run = bool(cli_template) and can_start
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("Download Narrative QA Instruction", prompt, file_name=f"{project.name}_narrative-qa.txt")
    with c2:
        if st.button("Run Narrative QA Agent", type="primary", disabled=not can_run):
            with st.spinner("Running Narrative QA Agent..."):
                result = run_external_command(cli_template, prompt, project)
            code, output = result.returncode, result.output
            if code == 0:
                st.session_state["gate_refresh_notice"] = "Narrative QA Agent completed. Gate status refreshed from the latest report."
                st.rerun()
            else:
                st.error(f"Narrative QA Agent exited with code {code}.")
                st.code(output or "No output", language="text")

    if output_ready:
        st.markdown("### Latest Narrative QA Report")
        report_text = safe_read_text(project / "14_narrative_qa.md")
        st.markdown(report_text)
        if "Current Text:" in report_text and "Replace With:" in report_text:
            if st.button("Apply Narrative Revisions", type="primary"):
                result = apply_revision_patch(project, "14_narrative_qa.md", log_dir=RUN_LOG_DIR)
                (st.success if result.success else st.error)(result.message)
                if result.backup_path: st.info(f"Backup: {Path(result.backup_path).relative_to(project)}")
    elif not cli_template:
        st.info("Codex CLI was not found. Install/login to Codex CLI, or set codex_cli_command in config.json.")

def render_medical_gate_2() -> None:
    st.subheader("Medical Gate 2")
    if st.session_state.get("gate_refresh_notice"):
        st.success(st.session_state.pop("gate_refresh_notice"))
    project = project_selector("medical_gate_2")
    if not project:
        return
    config = load_config()
    report = get_gate_status(project, "Medical Gate 2", config)
    c1, c2, c3 = st.columns(3)
    c1.metric("Final Script", "READY" if (project / "06_final_script.md").exists() else "MISSING")
    c2.metric("Evidence", "READY" if (project / "02_research_sheet.md").exists() else "MISSING")
    c3.metric("Gate Status", report.status)
    default_prompt = command_for_stage(project, "Medical Gate 2")
    prompt = sync_project_prompt_state(
        st.session_state,
        prompt_key="medical_gate_2_prompt",
        context_key="medical_gate_2_prompt_project",
        context_value=project.name,
        default_prompt=default_prompt,
    )
    prompt = st.text_area("Medical Gate 2 instruction", height=220, key="medical_gate_2_prompt")
    cli = detect_codex_command()
    ready, reasons = stage_ready(project, "Medical Gate 2", config)
    if not ready: st.warning("Medical Gate 2 is blocked. " + " ".join(reasons))
    can_run = bool(cli) and ready and (project / "02_research_sheet.md").exists()
    if st.button("Run Medical Gate 2", type="primary", disabled=not can_run):
        with st.spinner("Running Medical Gate 2..."):
            result = run_external_command(cli, prompt, project)
        if result.returncode == 0:
            st.session_state["gate_refresh_notice"] = "Medical Gate 2 completed. Gate status refreshed from the latest report."
            st.rerun()
        st.error(f"Medical Gate 2 exit code: {result.returncode}")
        st.code(result.output or "No output")
    path = project / config.get("medical_gate_2_output", "15_medical_gate_2.md")
    if path.exists():
        st.markdown("### Latest Report")
        report_text = safe_read_text(path)
        st.markdown(report_text)
        if "Current Text:" in report_text and "Replace With:" in report_text:
            if st.button("Apply Medical Revisions", type="primary"):
                result = apply_revision_patch(project, path.name, log_dir=RUN_LOG_DIR)
                (st.success if result.success else st.error)(result.message)
                if result.backup_path: st.info(f"Backup: {Path(result.backup_path).relative_to(project)}")


def render_speech_optimizer() -> None:
    st.subheader("Speech Optimizer")
    if st.session_state.get("gate_refresh_notice"):
        st.success(st.session_state.pop("gate_refresh_notice"))
    project = project_selector("speech_optimizer")
    if not project:
        return
    config = load_config()
    ready, reasons = stage_ready(project, "Speech Optimizer", config)
    blocked = not ready
    if blocked:
        st.warning("Speech Optimizer requires a non-empty 06_final_script.md. " + " ".join(reasons))
    default_prompt = command_for_stage(project, "Speech Optimizer")
    prompt = sync_project_prompt_state(
        st.session_state,
        prompt_key="speech_optimizer_prompt",
        context_key="speech_optimizer_prompt_project",
        context_value=project.name,
        default_prompt=default_prompt,
    )
    prompt = st.text_area("Speech Optimizer instruction", height=220, key="speech_optimizer_prompt")
    cli = detect_codex_command()
    if st.button("Run Speech Optimizer", type="primary", disabled=blocked or not cli):
        with st.spinner("Optimizing speech delivery..."):
            result = run_external_command(cli, prompt, project)
        (st.success if result.returncode == 0 else st.error)(f"Speech Optimizer exit code: {result.returncode}")
        st.code(result.output or "No output")
    c1, c2 = st.columns(2)
    c1.metric("Voice Script", "READY" if (project / "06a_voice_script.md").exists() else "MISSING")
    c2.metric("Voice Checklist", "READY" if (project / "06b_voice_checklist.md").exists() else "MISSING")


def render_qa_dashboard() -> None:
    st.subheader("Advanced QA Dashboard")
    project = project_selector("qa_dashboard")
    if not project: return
    config = load_config()
    rows = qa_dashboard(project, config)
    badge_colors={"PASS":"#1f9d55","PASS WITH REVISIONS":"#d69e2e","PASS WITH SUGGESTIONS":"#d69e2e","FAIL":"#d64545","MISSING":"#6b7280","UNKNOWN":"#6b7280"}
    selected_report=None
    for index,row in enumerate(rows):
        c1,c2,c3,c4,c5=st.columns([1.5,1.4,.7,1.6,1.2])
        c1.markdown(f"**{row['Stage']}**")
        color=badge_colors.get(row['Status'],"#6b7280")
        c2.markdown(f"<span style='background:{color};color:white;padding:4px 10px;border-radius:12px;font-weight:700'>{row['Status']}</span>",unsafe_allow_html=True)
        c3.metric("Issues",row['Issues'])
        c4.caption(f"Last run: {row['Last Run']} · Report: {row['Report']}")
        if c5.button("Open report",key=f"qa_open_{index}_{project.name}"):
            selected_report=row['Report']
        st.divider()
    report_options=[row['Report'] for row in rows]
    if selected_report:
        st.session_state[f"qa_selected_report_{project.name}"]=selected_report
    current=st.session_state.get(f"qa_selected_report_{project.name}",report_options[0])
    if current not in report_options: current=report_options[0]
    chosen=st.selectbox("Report viewer",report_options,index=report_options.index(current),key=f"qa_report_select_{project.name}")
    st.session_state[f"qa_selected_report_{project.name}"]=chosen
    path=project/chosen
    if path.exists():
        st.markdown(f"### {chosen}")
        st.markdown(safe_read_text(path))
    else: st.info(f"{chosen} is not available yet.")

def render_production_lock() -> None:
    st.subheader("Production Lock")
    selected_project = project_selector("production_lock")
    if not selected_project:
        return
    project = sync_project_validation_context(
        st.session_state,
        context_key="production_lock_selected_project",
        selected_project=selected_project,
        invalidate_keys=("production_lock_rows", "production_lock_reasons"),
    )
    config = load_config()
    prerequisites_ok, prerequisite_reasons = production_cleaner_prerequisites(project, config)
    cleaner_result = ensure_production_cleaner(project, config, log_dir=RUN_LOG_DIR)
    if cleaner_result is not None:
        if cleaner_result.success:
            st.success("Production Cleaner ran automatically and passed.")
        else:
            st.error("Production Cleaner ran automatically and failed.")
            for issue in cleaner_result.issues: st.write(f"- {issue}")
    lock = production_lock(project, config)
    if lock.locked:
        st.error("Production is LOCKED.")
    else:
        st.success("READY FOR PRODUCTION")
    rows = [{"Check": c.name, "Status": c.status, "File": c.file, "Reason": c.reason} for c in lock.checks]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", key=f"production_lock_checks_{project.name}")
    if lock.reasons:
        st.markdown("### Blocking reasons")
        for reason in lock.reasons:
            st.write(f"- {reason}")
    if prerequisites_ok:
        label = "Run Production Cleaner Again" if production_cleaner_is_current(project, config) else "Run Production Cleaner"
        if st.button(label, type="primary", key=f"production_lock_cleaner_{project.name}"):
            clean=ensure_production_cleaner(project,config,log_dir=RUN_LOG_DIR,force=True)
            if clean and clean.success: st.success("Production Cleaner: PASS")
            elif clean:
                st.error("Production Cleaner: FAIL")
                for issue in clean.issues: st.write(f"- {issue}")
            st.rerun()
    else:
        st.info("Production Cleaner is waiting for prerequisites.")
        for reason in prerequisite_reasons: st.write(f"- {reason}")


def render_production() -> None:
    st.subheader("Production Mix")
    project = project_selector("production")
    if not project:
        return
    config = load_config()

    st.markdown("### Production Cleaner")
    prerequisites_ok, prerequisite_reasons = production_cleaner_prerequisites(project, config)
    if prerequisites_ok:
        if not production_cleaner_is_current(project, config):
            clean = ensure_production_cleaner(project, config, log_dir=RUN_LOG_DIR)
            if clean and clean.success:
                st.success("Production Cleaner: PASS")
            elif clean:
                st.error("Production Cleaner: FAIL")
                for issue in clean.issues:
                    st.write(f"- {issue}")
        if st.button("Run Production Cleaner Again", type="primary", key=f"production_cleaner_again_{project.name}"):
            clean = ensure_production_cleaner(project, config, log_dir=RUN_LOG_DIR, force=True)
            if clean and clean.success:
                st.success("Production Cleaner: PASS")
            elif clean:
                st.error("Production Cleaner: FAIL")
                for issue in clean.issues:
                    st.write(f"- {issue}")
            st.rerun()
    else:
        st.info("Production Cleaner cannot run until prerequisites pass.")
        for reason in prerequisite_reasons:
            st.write(f"- {reason}")

    cleaner_report = project / "production_clean_report.md"
    if cleaner_report.exists():
        st.markdown(safe_read_text(cleaner_report))

    lock = production_lock(project, config)
    if lock.locked:
        st.error("Production is locked. Complete every Production Lock 2.0 checklist item first.")
        for reason in lock.reasons:
            st.write(f"- {reason}")
    else:
        st.success("READY FOR PRODUCTION")

    settings_path = project / "production_settings.json"
    defaults = {"avatar": 40, "ai_images": 30, "stock": 10, "overlays": 20, "image_duration_seconds": 10, "image_platform": "Genspark Web"}
    try:
        settings = {**defaults, **json.loads(safe_read_text(settings_path) or "{}")}
    except json.JSONDecodeError:
        settings = defaults

    c1, c2, c3, c4 = st.columns(4)
    avatar = c1.number_input("Avatar %", 0, 100, int(settings["avatar"]))
    ai_images = c2.number_input("AI Images %", 0, 100, int(settings["ai_images"]))
    stock = c3.number_input("Stock %", 0, 100, int(settings["stock"]))
    overlays = c4.number_input("Overlays %", 0, 100, int(settings["overlays"]))
    total = avatar + ai_images + stock + overlays
    mix_valid, mix_reason = validate_production_mix(avatar, ai_images, stock, overlays)
    st.metric("Total", f"{total}%")

    duration = st.number_input("AI image display duration (seconds)", 6, 20, int(settings["image_duration_seconds"]))
    options = ["Genspark Web", "Midjourney", "ChatGPT", "Other"]
    current_platform = settings.get("image_platform", "Genspark Web")
    platform = st.selectbox("Image platform", options, index=options.index(current_platform) if current_platform in options else 0)

    voice_script = safe_read_text(project / "06a_voice_script.md")
    if voice_script:
        minutes = count_words(voice_script) / max(1, int(config.get("narration_words_per_minute", 150)))
        estimated_images = round((minutes * 60 * ai_images / 100) / max(1, duration))
        st.info(f"Estimated runtime: {minutes:.1f} minutes · Estimated AI images: approximately {estimated_images}")
    else:
        st.info("Runtime estimate will appear when 06a_voice_script.md is available.")

    payload = {
        "avatar": avatar, "ai_images": ai_images, "stock": stock, "overlays": overlays,
        "image_duration_seconds": duration, "image_platform": platform,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if st.button("Save Production Mix", disabled=not mix_valid):
        if safe_write_text(settings_path, json.dumps(payload, indent=2) + "\n"):
            st.success("Production mix saved.")
    if not mix_valid:
        st.warning(mix_reason)

    cli_template = detect_codex_command()
    direct_enabled = bool(config.get("direct_run_enabled", True)) and bool(cli_template)
    generation_reasons = []
    if lock.locked:
        generation_reasons.append("Production Lock is not READY.")
    if not mix_valid:
        generation_reasons.append(mix_reason)
    if not direct_enabled:
        generation_reasons.append("Codex CLI is unavailable or Direct Codex Run is disabled in configuration.")

    st.markdown("### Generate Production Outputs")
    generate_disabled = bool(generation_reasons)
    if generation_reasons:
        for reason in generation_reasons:
            st.caption(f"• {reason}")

    if st.button("Generate Production Plan", type="primary", disabled=generate_disabled, key=f"generate_production_{project.name}"):
        if not safe_write_text(settings_path, json.dumps(payload, indent=2) + "\n"):
            st.error("Production generation was not started because production settings could not be saved.")
        else:
            try:
                clear_stale_production_outputs(project)
            except RuntimeError as exc:
                st.error(str(exc))
                result = None
            else:
                prompt = command_for_stage(project, "Production Package")
                try:
                    with st.spinner("Generating production outputs..."):
                        result = run_external_command(cli_template, prompt, project)
                except Exception as exc:
                    st.error(f"Production generation could not start: {type(exc).__name__}. Check the Codex CLI configuration and run log.")
                    result = None
            if result is None:
                pass
            else:
                outputs = production_outputs(project)
                source_ok = False
                source_issues: list[str] = []
                if result.returncode == 0 and (project / "07_production_sheet.csv").is_file():
                    contract_ok, contract_issues = normalize_production_sheet(project / "07_production_sheet.csv")
                    if contract_ok:
                        sanitize_csv_file(
                            project / "07_production_sheet.csv",
                            required_text_columns=("script_excerpt",),
                        )
                        source_ok, source_issues = validate_production_sheet_against_voice(project)
                        segmentation_issues = production_sheet_segmentation_issues(project)
                        if segmentation_issues:
                            source_ok = False
                            source_issues = ["SCENE_SEGMENTATION_QA_FAILED"] + segmentation_issues
                    else:
                        source_ok = False
                        source_issues = list(contract_issues)
                semantic_audit = None
                prompt_output = project / "10_image_prompts.md"
                if result.returncode == 0 and prompt_output.is_file():
                    semantic_audit = enforce_final_semantic_report(prompt_output)
                if result.returncode == 0 and all(outputs.values()) and source_ok and (semantic_audit is None or semantic_audit.passed):
                    st.success("Production generation completed successfully.")
                elif result.returncode == 0 and not source_ok:
                    if source_issues and source_issues[0] == "SCENE_SEGMENTATION_QA_FAILED":
                        st.error("Production output rejected: scene segmentation/timing QA failed. The script source itself still matches 06a_voice_script.md.")
                        display_issues = source_issues[1:]
                    else:
                        st.error("Production output rejected: 07_production_sheet.csv failed the canonical Production/source contract.")
                        display_issues = source_issues
                    for issue in display_issues[:12]:
                        st.caption(f"• {issue}")
                elif result.returncode == 0 and semantic_audit is not None and not semantic_audit.passed:
                    ids = ", ".join(f"IMAGE {x.image_number:03d}" for x in semantic_audit.issues)
                    st.error("Production outputs were generated, but final Semantic Coherence verification failed: " + ids + ". 10_image_prompts.md is NOT PRODUCTION READY.")
                elif result.returncode == 0:
                    missing = [name for name, exists in outputs.items() if not exists]
                    st.warning("Production command completed, but expected output files are missing: " + ", ".join(missing))
                else:
                    st.error(f"Production generation failed with exit code {result.returncode}. Review log: {Path(result.log_path).name}")
                st.rerun()

    outputs = production_outputs(project)
    if any(outputs.values()):
        st.markdown("### Production Outputs")
        for filename, exists in outputs.items():
            if exists:
                path = project / filename
                st.success(f"Generated: {filename}")
                data = path.read_bytes()
                mime = "text/csv" if path.suffix.lower() == ".csv" else "text/markdown"
                st.download_button(f"Download {filename}", data, file_name=filename, mime=mime, key=f"download_{project.name}_{filename}")
            else:
                st.info(f"Pending: {filename}")

    render_avatar_timing_sync(project, config, lock_ready=not lock.locked)


def render_avatar_timing_sync(project: Path, config: dict[str, Any], lock_ready: bool) -> None:
    st.markdown("---")
    st.markdown("## Avatar Timing Sync")
    st.caption("Uses actual avatar speech timing after Production Lock. Approved narration files are read-only.")

    model_settings = transcription_settings(config)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Configured Model", model_settings["configured_model"])
    m2.metric("Effective Model", model_settings["effective_model"])
    m3.metric("Timestamp Mode", model_settings["timestamp_mode"])
    m4.metric("Word Timing", "Yes" if model_settings["word_timing_available"] else "No")
    st.caption(f"Model source: {model_settings['model_source']} · Response format: {model_settings['response_format']}")

    state_key = f"avatar_folder_{project.name}"
    default_folder = str((project / "avatars").resolve())
    folder_value = st.text_input("Avatar Folder", value=st.session_state.get(state_key, default_folder), key=f"avatar_folder_input_{project.name}")
    avatar_folder = Path(folder_value).expanduser()
    if not avatar_folder.is_absolute():
        avatar_folder = (project / avatar_folder).resolve()

    if st.button("Select Avatar Folder", disabled=not lock_ready, key=f"select_avatar_folder_{project.name}"):
        st.session_state[state_key] = str(avatar_folder)
        if avatar_folder.is_dir():
            st.success(f"Avatar folder selected: {avatar_folder}")
        else:
            st.error("The selected avatar folder does not exist.")

    discovery = discover_avatar_chunks(avatar_folder) if avatar_folder.is_dir() else None
    scenes = load_production_scenes(project / "07_production_sheet.csv")
    production_source_ok = True
    production_source_issues: list[str] = []
    if scenes:
        production_source_ok, production_source_issues = validate_production_sheet_against_voice(project)
        if not production_source_ok:
            scenes = []
            st.warning("07_production_sheet.csv does not match the current 06a_voice_script.md. Regenerate Production Plan before avatar timing.")
            for issue in production_source_issues[:8]:
                st.caption(f"• {issue}")
        else:
            segmentation_issues = production_sheet_segmentation_issues(project)
            if segmentation_issues:
                st.warning("Production sheet narration matches 06a_voice_script.md, but scene segmentation/timing has QA warnings. Avatar timing may continue because real transcript timing will replace provisional scene timing.")
                for issue in segmentation_issues[:6]:
                    st.caption(f"• {issue}")
    sequence = chunk_sequence_info(discovery)
    chunks_found = sequence.detected_count
    transcript_dir = project / "avatar_transcripts"
    inventory = transcript_inventory(discovery.chunks, transcript_dir, config) if discovery else {"current": 0, "total_duration": 0.0}
    timeline_path = project / "08_actual_timeline.csv"
    manifest_path = project / "avatar_timing_manifest.json"
    report_path = project / "avatar_alignment_report.md"

    alignment_score = None
    timeline_status = "NOT GENERATED"
    if manifest_path.is_file():
        try:
            manifest = json.loads(safe_read_text(manifest_path) or "{}")
            alignment_score = float(manifest.get("alignment_score", 0.0))
            timeline_status = str(manifest.get("timeline_status", "UNKNOWN"))
        except (json.JSONDecodeError, TypeError, ValueError):
            timeline_status = "INVALID MANIFEST"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Detected Chunks", chunks_found)
    c2.metric("First Chunk", sequence.first_chunk or "None")
    c3.metric("Last Chunk", sequence.last_chunk or "None")
    c4.metric("Expected Sequential Chunks", sequence.expected_count)
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Missing Chunk Numbers", ", ".join(map(str, sequence.missing_numbers)) if sequence.missing_numbers else "None")
    d2.metric("Total Avatar Duration", f"{inventory['total_duration'] / 60:.2f} min" if inventory["total_duration"] else "Pending")
    d3.metric("Total Production Scenes", len(scenes))
    d4.metric("Transcribed Chunks", f"{inventory['current']}/{chunks_found}" if chunks_found else "0")
    e1, e2, e3 = st.columns(3)
    e1.metric("Reused Cached Chunks", inventory["current"])
    e2.metric("Alignment Score", f"{alignment_score:.1f}%" if alignment_score is not None else "Pending")
    e3.metric("Timeline Status", timeline_status)

    blockers = avatar_sync_blockers(lock_ready, avatar_folder, scenes, discovery)
    if discovery:
        if discovery.unsupported:
            st.warning("Unsupported files: " + ", ".join(discovery.unsupported))
        if discovery.duplicates:
            st.warning("Duplicate/alternative chunks detected: " + " | ".join(discovery.duplicates))

    for reason in blockers:
        st.caption(f"• {reason}")

    error_key = f"avatar_transcription_error_{project.name}"
    if discovery and discovery.chunks:
        rows = preflight_avatar_chunks(discovery.chunks, transcript_dir, config)
        st.dataframe(
            pd.DataFrame([{
                "Chunk": row["chunk"], "Size MB": row["size_mb"],
                "Status": row["status"], "Action": row["action"],
            } for row in rows]),
            hide_index=True, use_container_width=True,
        )

    saved_error = st.session_state.get(error_key)
    if saved_error:
        st.error(f"Avatar transcription failed on {saved_error.get('failed_chunk', 'unknown chunk')}: {saved_error.get('exception_class')}: {saved_error.get('message')}")
        st.write({
            "Failed chunk filename": saved_error.get("failed_chunk"),
            "Exception class": saved_error.get("exception_class"),
            "Exception message": saved_error.get("message"),
            "File size MB": saved_error.get("file_size_mb"),
            "Configured model": saved_error.get("configured_model"),
            "Effective model": saved_error.get("effective_model"),
            "Response format": saved_error.get("response_format"),
            "Timestamp granularities": saved_error.get("timestamp_granularities"),
            "API key detected": "Yes" if saved_error.get("api_key_detected") else "No",
            "Output directory": saved_error.get("output_directory"),
        })
        with st.expander("Technical Error Details"):
            st.code(saved_error.get("traceback", "No traceback captured."), language="text")
        if st.button("Clear Error", key=f"clear_avatar_error_{project.name}"):
            st.session_state.pop(error_key, None)
            st.rerun()

    transcribe_disabled = bool(blockers)
    if st.button("Transcribe Avatar Chunks", type="primary", disabled=transcribe_disabled, key=f"transcribe_avatars_{project.name}"):
        progress_box = st.empty()
        try:
            with st.spinner("Transcribing new or modified avatar chunks..."):
                result = transcribe_avatar_chunks(
                    discovery.chunks, transcript_dir, config,
                    progress=lambda message: progress_box.info(message),
                )
        except Exception as exc:
            trace = traceback.format_exc()
            logging.exception("Avatar transcription failed")
            log_path = transcript_dir / "avatar_transcription_error.log"
            try:
                transcript_dir.mkdir(parents=True, exist_ok=True)
                log_path.write_text(trace, encoding="utf-8", newline="\n")
            except OSError:
                logging.exception("Could not persist avatar transcription traceback to %s", log_path)
            settings = transcription_settings(config)
            details = getattr(exc, "details", {}) if isinstance(exc, AvatarTranscriptionError) else {}
            failed_chunk = details.get("failed_chunk") or getattr(getattr(exc, "chunk", None), "name", None)
            st.session_state[error_key] = {
                "failed_chunk": failed_chunk,
                "exception_class": type(exc.__cause__ or exc).__name__,
                "message": str(exc.__cause__ or exc),
                "file_size_mb": details.get("file_size_mb"),
                "configured_model": settings["configured_model"],
                "effective_model": settings["effective_model"],
                "response_format": settings["response_format"],
                "timestamp_granularities": settings["timestamp_granularities"],
                "api_key_detected": details.get("api_key_detected", bool(os.getenv(str(config.get("openai_api_key_env", "OPENAI_API_KEY"))))),
                "output_directory": str(transcript_dir),
                "traceback": trace,
            }
            st.rerun()
        else:
            st.session_state.pop(error_key, None)
            progress_box.success("All avatar chunks completed.")
            st.success(f"Transcription complete. Transcribed: {result.transcribed} · Reused: {result.reused} · Skipped: {result.skipped}")
            st.rerun()

    all_transcripts_present = bool(discovery and discovery.chunks) and all(
        transcript_cache_is_current(chunk, transcript_dir, config)
        for chunk in discovery.chunks
    )
    timeline_blockers = list(blockers)
    if not all_transcripts_present:
        timeline_blockers.append("Every avatar chunk must have current JSON and SRT outputs for the effective transcription model/settings.")

    if st.button("Build Actual Timeline", disabled=bool(timeline_blockers), key=f"build_actual_timeline_{project.name}"):
        try:
            with st.spinner("Aligning approved narration to actual spoken timing..."):
                result = build_actual_timeline(project, avatar_folder, config, transcript_dir=transcript_dir)
        except Exception as exc:
            st.error(f"Actual timeline generation failed: {type(exc).__name__}. Review avatar transcripts and production sheet.")
        else:
            if result.success:
                st.success(f"Actual timeline generated with {result.rows} scenes. Alignment: {result.alignment_score:.1f}%")
                if result.warnings:
                    for warning in result.warnings:
                        st.warning(warning)
            else:
                st.error("Actual timeline was not generated because validation failed.")
                for item in result.missing_chunks + result.duplicate_chunks + result.warnings:
                    st.caption(f"• {item}")
            st.rerun()

    generated = [timeline_path, manifest_path, report_path]
    if any(path.is_file() for path in generated):
        st.markdown("### Avatar Timing Outputs")
        for path in generated:
            if path.is_file():
                mime = "text/csv" if path.suffix == ".csv" else ("application/json" if path.suffix == ".json" else "text/markdown")
                st.success(f"Generated: {path.name}")
                st.download_button(f"Download {path.name}", path.read_bytes(), file_name=path.name, mime=mime, key=f"download_avatar_timing_{project.name}_{path.name}")

    st.markdown("---")
    st.markdown("## Timeline Builder & CapCut Export")
    capcut_dir = project / "capcut"
    capcut_manifest = capcut_dir / "timeline_manifest.json"
    capcut_report = capcut_dir / "export_report.md"
    timeline_pass = timeline_path.is_file() and timeline_status == "PASS"
    if not timeline_path.is_file():
        st.caption("• 08_actual_timeline.csv must exist.")
    if timeline_path.is_file() and timeline_status != "PASS":
        st.caption("• Avatar Timeline status must be PASS.")
    if st.button("Generate CapCut Project", type="primary", disabled=not timeline_pass, key=f"generate_capcut_{project.name}"):
        try:
            with st.spinner("Building generic timeline manifest and CapCut Desktop project..."):
                built = build_timeline_manifest(project, timeline_path)
                exported = export_capcut_project(project, built.manifest_path)
        except (TimelineBuildError, CapCutExportError) as exc:
            st.error(f"CapCut export failed: {exc}")
        except FileNotFoundError as exc:
            logging.exception("CapCut export failed because a required filesystem path disappeared")
            capcut_dir.mkdir(parents=True, exist_ok=True)
            missing_path = getattr(exc, "filename", None) or str(exc)
            capcut_report.write_text(
                "# CapCut Export Report\n\n"
                "- Status: **FAIL**\n"
                "- Error: `FileNotFoundError`\n"
                f"- Missing path: `{missing_path}`\n"
                f"- Project root: `{project}`\n\n"
                "The exporter stopped before replacing the working project. "
                "Regenerate after confirming the reported path exists.\n",
                encoding="utf-8",
                newline="\n",
            )
            st.error(f"CapCut export failed: missing path {missing_path}. Review capcut/export_report.md.")
        except Exception as exc:
            logging.exception("CapCut export failed")
            st.error(f"CapCut export failed: {type(exc).__name__}. Review capcut/export_report.md.")
        else:
            
            if exported.warnings:
                st.warning("CapCut project generated: PROJECT GENERATED / PREVIEW READY. Visible image/B-roll placeholders remain and must be replaced before final production.")
                for warning in exported.warnings:
                    st.caption(f"• {warning}")
            else:
                st.success(f"CapCut project generated: FINAL ASSETS READY. Base avatar duration {exported.duration_seconds:.3f} seconds.")
            st.rerun()

    capcut_outputs = [capcut_manifest, capcut_dir / "asset_manifest.json", capcut_report,
                      capcut_dir / "CapCut_Project" / "draft_content.json",
                      capcut_dir / "CapCut_Project" / "draft_meta_info.json"]
    if any(path.is_file() for path in capcut_outputs):
        st.markdown("### CapCut Outputs")
        for path in capcut_outputs:
            if path.is_file():
                mime = "application/json" if path.suffix == ".json" else "text/markdown"
                st.success(f"Generated: {path.relative_to(project)}")
                st.download_button(f"Download {path.name}", path.read_bytes(), file_name=path.name, mime=mime, key=f"download_capcut_{project.name}_{path.name}_{len(str(path))}")


def load_production_sheet(path: Path) -> pd.DataFrame:
    try: return pd.read_csv(path)
    except Exception: return pd.DataFrame()


def find_asset_type_column(df: pd.DataFrame) -> str | None:
    for c in ["recommended_asset_type", "asset_type", "visual_type", "scene_type", "Asset Type", "Visual Type"]:
        if c in df.columns: return c
    return next((c for c in df.columns if "asset" in c.lower() and "type" in c.lower()), None)


def render_opus_image_prompt_import() -> None:
    st.subheader("Opus Image Prompt Import")
    project = project_selector("opus_image_prompt_import")
    if project is None:
        return

    st.caption(f"Selected Project: {project.name}")
    try:
        slots = load_production_ai_image_slots(project)
    except (FileNotFoundError, ValueError, UnicodeError) as exc:
        st.error(str(exc))
        return

    st.metric("Production AI_IMAGE Count", len(slots))
    st.caption(f"Authoritative Production source: {project / '07_production_sheet.csv'}")
    st.caption("Opus CSV Timing is legacy/reference-only and is never used by this importer.")

    existing_output = project / "10_image_prompts.md"
    if existing_output.is_file():
        st.warning("10_image_prompts.md already exists. Generating will replace it after creating a timestamped Backups/ copy.")

    uploaded = st.file_uploader("Upload Opus Prompt CSV", type=["csv"], key=f"opus_prompt_csv_{project.name}")
    if uploaded is None:
        st.info("Upload an Opus prompt CSV to validate mapping against the current project's Production Sheet.")
        return

    payload = uploaded.getvalue()
    try:
        validation = validate_import(project, payload)
    except (ValueError, UnicodeError, csv.Error) as exc:
        st.error(f"Could not parse Opus CSV: {exc}")
        return

    c1, c2 = st.columns(2)
    c1.metric("Imported Prompt Count", validation.imported_count)
    c2.metric("Validation Status", "PASS" if validation.passed else "FAIL")

    preview = pd.DataFrame([
        {
            "IMAGE": f"IMAGE {row.image_number:03d}",
            "Scene ID": row.scene_id,
            "Production Script Line": row.production_script_line,
            "Opus Script Line": row.opus_script_line,
            "Scene Type": row.scene_type,
            "Match Status": row.match_status,
        }
        for row in validation.mappings
    ])
    if not preview.empty:
        st.dataframe(preview, hide_index=True, width="stretch", key=f"opus_import_preview_{project.name}")

    if validation.errors:
        for error in validation.errors:
            st.error(error)

    generated_key = f"opus_generated_path_{project.name}"
    if st.button("Generate 10_image_prompts.md", type="primary", disabled=not validation.passed, key=f"generate_opus_prompts_{project.name}"):
        try:
            output, backup, _ = write_image_prompts(project, payload)
            st.session_state[generated_key] = str(output)
            st.success("10_image_prompts.md generated from the imported Opus prompts.")
            if backup:
                st.info(f"Backup created: {backup.relative_to(project)}")
        except (OSError, ValueError, UnicodeError) as exc:
            st.error(f"Could not generate 10_image_prompts.md: {exc}")

    generated = Path(st.session_state.get(generated_key, "")) if st.session_state.get(generated_key) else existing_output
    if generated.is_file() and validation.passed:
        st.download_button(
            "Download 10_image_prompts.md",
            data=generated.read_bytes(),
            file_name="10_image_prompts.md",
            mime="text/markdown",
            key=f"download_opus_prompts_{project.name}",
        )


def render_images() -> None:
    st.subheader("Image Generation")
    project = project_selector("images")
    if not project:
        return
    # Project path and all downstream state are resolved fresh on every Streamlit rerun/action.
    project = project.resolve()
    config = load_config()
    try:
        assignments = load_production_image_assignments(project)
    except ValueError as exc:
        st.error(str(exc)); return
    if not assignments:
        st.info("10_image_prompts.md is missing or has no Final AI IMAGE PROMPT entries. Generate the Production Package first.")
        return

    manifest = reconcile_manifest(project, assignments)
    records = manifest.get("images", {})
    generated = sum(1 for a in assignments if a.asset_path.is_file())
    stale_count = sum(1 for a in assignments if records.get(a.filename, {}).get("status") == "STALE")
    failed_count = sum(1 for a in assignments if records.get(a.filename, {}).get("status") == "FAILED")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("AI images required", len(assignments)); c2.metric("Already generated", generated)
    c3.metric("Remaining", len(assignments)-generated); c4.metric("Stale / Failed", f"{stale_count} / {failed_count}")
    st.caption(f"Production prompt source: {project / '10_image_prompts.md'} · Asset destination: {project / 'assets' / 'images'}")

    profiles = model_profiles_from_config(config)
    keys = list(profiles)
    default_key = str(config.get("image_generation_default_model", DEFAULT_MODEL_KEY))
    if default_key not in profiles: default_key = DEFAULT_MODEL_KEY if DEFAULT_MODEL_KEY in profiles else keys[0]
    model_key = st.selectbox("Image Model", keys, index=keys.index(default_key), format_func=lambda k: profiles[k].display_name, key=f"image_model_{project.name}")
    profile = profiles[model_key]
    enhancement = st.toggle("Prompt Enhancement", value=True, key=f"image_enhancement_{project.name}")
    st.caption(f"Provider: {profile.provider} · Model ID: {profile.model_id} · Output: {profile.dimensions[0]}×{profile.dimensions[1]} (16:9)")
    if not os.getenv("RUNWARE_API_KEY"):
        st.warning("RUNWARE_API_KEY is not configured. Preview/status works, but API generation is disabled.")

    remaining = len(select_missing(assignments))
    if profile.cost_per_image is not None:
        st.info(f"Estimated cost for {remaining} missing images: approximately ${remaining * profile.cost_per_image:.4f} (configuration-driven estimate).")

    st.markdown("### Prompt Preview")
    chosen_name = st.selectbox("Image", [a.filename for a in assignments], key=f"image_preview_{project.name}")
    chosen = next(a for a in assignments if a.filename == chosen_name)
    st.text_area("Original Production Prompt", chosen.original_prompt, height=180, disabled=True, key=f"original_prompt_{project.name}_{chosen_name}")
    st.text_area("Enhanced Generation Prompt", enhance_prompt(chosen.original_prompt, profile, enhancement), height=220, disabled=True, key=f"enhanced_prompt_{project.name}_{chosen_name}_{model_key}_{enhancement}")
    rec = records.get(chosen_name, {})
    if rec: st.caption(f"Status: {rec.get('status','PENDING')} · Previous model: {rec.get('selected_model','Unknown')} · Attempts: {rec.get('attempts',0)}")

    generated_names = [a.filename for a in assignments if a.asset_path.is_file()]
    selected_regen = st.multiselect("Select images to regenerate", generated_names, key=f"regen_images_{project.name}")
    retry_count = int(config.get("image_generation_retry_count", 2)); concurrency = int(config.get("image_generation_concurrency", 3))

    def run_generation(targets, label):
        if not targets: st.info(f"No images need {label.lower()}."); return
        if not os.getenv("RUNWARE_API_KEY"): st.error("RUNWARE_API_KEY is not configured."); return
        bar=st.progress(0); status=st.empty()
        def progress(done,total,result):
            bar.progress(done/total); status.write(f"{done} / {total} · {result.assignment.filename}: {result.status}")
        with st.spinner(f"{label}..."):
            results=generate_batch(project, targets, profile, enhancement, retry_count=retry_count, max_workers=concurrency, progress=progress)
        ok=sum(r.status=="SUCCESS" for r in results); bad=len(results)-ok
        (st.success if not bad else st.warning)(f"Completed: {ok} successful, {bad} failed.")
        st.rerun()

    b1,b2,b3,b4 = st.columns(4)
    if b1.button("Generate Missing Images", type="primary", key=f"gen_missing_{project.name}"):
        run_generation(select_missing(load_production_image_assignments(project)), "Generate Missing Images")
    if b2.button("Regenerate Selected", disabled=not selected_regen, key=f"regen_selected_{project.name}"):
        current=load_production_image_assignments(project); run_generation([a for a in current if a.filename in selected_regen], "Regenerate Selected")
    if b3.button("Retry Failed", key=f"retry_failed_{project.name}"):
        current=load_production_image_assignments(project); run_generation(select_failed_or_missing(project, current), "Retry Failed")
    if b4.button("Regenerate Stale Images", disabled=stale_count==0, key=f"regen_stale_{project.name}"):
        current=load_production_image_assignments(project); run_generation(select_stale(project, current), "Regenerate Stale Images")

    if st.button("Regenerate All With Current Model", key=f"regen_all_{project.name}"):
        run_generation(load_production_image_assignments(project), "Regenerate All")

    manifest = load_manifest(project)
    rows=[]
    for a in assignments:
        r=manifest.get("images",{}).get(a.filename,{})
        rows.append({"Image":a.filename,"Scene":a.scene_id,"Status":r.get("status","PENDING"),"Model":r.get("selected_model",""),"Attempts":r.get("attempts",0),"Error":r.get("safe_error_summary","")})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    zip_bytes=build_images_zip(project, assignments)
    st.download_button("Download Images ZIP", zip_bytes, file_name=f"{project.name}_images.zip", mime="application/zip", key=f"download_images_zip_{project.name}")


def render_text_overlay_import() -> None:
    st.subheader("Text Overlay Import")
    project = project_selector("text_overlay_import")
    if not project: return
    timeline_path = project / "08_actual_timeline.csv"
    artifact_path = project / ARTIFACT_NAME
    st.caption(f"Selected Project: {project.name}")
    st.caption(f"Authoritative Narration Source: {timeline_path}")
    st.caption(f"Actual Timeline Status: {'READY' if timeline_path.is_file() else 'MISSING'}")
    uploaded = st.file_uploader("Upload Opus Text Overlay CSV", type=["csv"], key=f"overlay_upload_{project.name}")
    state_key=f"overlay_validation_{project.name}"
    if uploaded is not None:
        try:
            rows=parse_opus_csv(uploaded.getvalue())
            st.metric("Imported Overlay Count", len(rows))
            if st.button("Validate Overlay CSV", type="primary", key=f"validate_overlay_{project.name}"):
                result=validate_rows(project, rows); st.session_state[state_key]=(rows,result)
        except Exception as exc:
            st.error(str(exc)); st.session_state.pop(state_key,None)
    else:
        st.metric("Imported Overlay Count", 0)

    saved=st.session_state.get(state_key)
    result=saved[1] if saved else None
    st.metric("Validation Status", "PASS" if result and result.passed else ("FAIL" if result else "NOT RUN"))
    if result:
        preview=[]
        for r in result.records:
            preview.append({"Overlay":r.overlay_number,"Type":r.overlay_type,"Script Line Start":r.script_line_start,"Script Line End":r.script_line_end,"Overlay Text":r.overlay_text,"Timing Match":r.timing_source,"Start":r.start_seconds,"End":r.end_seconds,"Status":r.status})
        st.dataframe(pd.DataFrame(preview), hide_index=True, use_container_width=True)
        for error in result.errors: st.error(error)
        for warning in result.warnings: st.warning(warning)
    if artifact_path.exists(): st.warning(f"{ARTIFACT_NAME} already exists. Regeneration will create a timestamped backup first.")
    generate_disabled=not (result and result.passed)
    if st.button("Generate Text Overlay Artifact", disabled=generate_disabled, key=f"generate_overlay_{project.name}"):
        try:
            path=write_artifact(project,result); st.success(f"Generated: {path.name}")
        except Exception as exc: st.error(str(exc))
    if artifact_path.is_file():
        st.download_button("Download Text Overlay Artifact", artifact_path.read_bytes(), file_name=artifact_path.name, mime="text/csv", key=f"download_overlay_{project.name}")


def render_files() -> None:
    st.subheader("File Manager")
    project = project_selector("files")
    if not project: return
    files = sorted([p for p in project.rglob("*") if p.is_file() and p.suffix.lower() in VIEWABLE_SUFFIXES], key=lambda p: str(p).lower())
    if not files: st.info("No viewable files found."); return
    labels = [str(p.relative_to(project)) for p in files]; name = st.selectbox("File", labels); path = project / name
    if path.suffix.lower() == ".csv":
        try: st.dataframe(pd.read_csv(path), width="stretch")
        except Exception as exc: st.error(str(exc))
        st.download_button("Download", path.read_bytes(), file_name=path.name); return
    text = safe_read_text(path); edited = st.text_area("Content", text, height=560); c1, c2 = st.columns(2)
    if c1.button("Save", type="primary") and path.suffix.lower() in EDITABLE_SUFFIXES:
        if path.suffix.lower() == ".json":
            try: edited = json.dumps(json.loads(edited), indent=2, ensure_ascii=False) + "\n"
            except json.JSONDecodeError as exc: st.error(f"Invalid JSON: {exc}"); return
        safe_write_text(path, edited); st.success("Saved.")
    c2.download_button("Download", text, file_name=path.name)


def render_config() -> None:
    st.subheader("System Configuration")
    config = load_config(); config.setdefault("production_defaults", {"avatar": 40, "ai_images": 30, "stock": 10, "overlays": 20})
    st.markdown("### General")
    config["channel_name"] = st.text_input("Channel name", config.get("channel_name", "")); config["host_name"] = st.text_input("Host name", config.get("host_name", "")); config["target_runtime_minutes"] = st.number_input("Target runtime", 5, 60, int(config.get("target_runtime_minutes", 25)))
    st.markdown("### Codex CLI")
    config["codex_cli_command"] = st.text_input("CLI command template", config.get("codex_cli_command", ""), help='Recommended: codex.cmd exec --sandbox workspace-write --skip-git-repo-check {prompt}')
    config["direct_run_enabled"] = st.checkbox("Direct Run enabled", bool(config.get("direct_run_enabled", True)))
    config["speech_optimizer_required_for_production"] = st.checkbox("Require Speech Optimizer before production", bool(config.get("speech_optimizer_required_for_production", True)))
    config["allow_production_override"] = st.checkbox("Allow manual Production Lock override", bool(config.get("allow_production_override", False)))
    st.markdown("### Raw JSON")
    raw = st.text_area("config.json", json.dumps(config, indent=2, ensure_ascii=False), height=440)
    if st.button("Validate and Save", type="primary"):
        try: parsed = json.loads(raw)
        except json.JSONDecodeError as exc: st.error(f"Invalid JSON: {exc}"); return
        save_config(parsed); st.success("Configuration saved.")


def render_analytics() -> None:
    st.subheader("Analytics"); ANALYTICS_DIR.mkdir(exist_ok=True); files = sorted([p for p in ANALYTICS_DIR.iterdir() if p.suffix.lower() in {".csv", ".json"}])
    if not files: st.info("Add YouTube analytics CSV or JSON files to Analytics/."); return
    name = st.selectbox("Analytics file", [p.name for p in files]); path = ANALYTICS_DIR / name
    if path.suffix.lower() == ".csv": st.dataframe(pd.read_csv(path), width="stretch")
    else: st.json(json.loads(safe_read_text(path)))


def main() -> None:
    st.set_page_config(page_title="Senior Health AI V3.3", page_icon="🎬", layout="wide")
    inject_css()
    st.title("Senior Health AI V3.3")
    st.caption("Auto Revision Engine · QA Dashboard · Production Cleaner · Production Lock 2.0 · Direct Codex Run")
    pages = ["Dashboard", "New Project", "Workflow", "Writer Workspace", "Narrative QA", "Medical Gate 2", "Speech Optimizer", "QA Dashboard", "Production Lock", "Production", "Opus Image Prompt Import", "Image Generation", "Text Overlay Import", "Files", "Analytics", "Config"]
    page = st.sidebar.radio("Navigation", pages)
    handlers = {
        "Dashboard": render_dashboard, "New Project": render_new_project, "Workflow": render_workflow,
        "Writer Workspace": render_writer_workspace, "Narrative QA": render_narrative_qa, "Medical Gate 2": render_medical_gate_2,
        "Speech Optimizer": render_speech_optimizer, "QA Dashboard": render_qa_dashboard, "Production Lock": render_production_lock,
        "Production": render_production, "Opus Image Prompt Import": render_opus_image_prompt_import, "Image Generation": render_images, "Text Overlay Import": render_text_overlay_import, "Files": render_files,
        "Analytics": render_analytics, "Config": render_config,
    }
    handlers[page]()


if __name__ == "__main__":
    main()
