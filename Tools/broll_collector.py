from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_FILE = "07_production_sheet.csv"
IMAGE_PROMPTS_FILE = "10_image_prompts.md"
BROLL_PROMPTS_FILE = "12_broll_prompts.md"
CONFIG_FILE = "config.json"
MANIFEST_FILE = "asset_manifest.csv"
CANDIDATE_DIAGNOSTICS_FILE = "candidate_diagnostics.csv"
VISION_CACHE_FILE = ".broll_vision_cache.json"
VISUAL_DIRECTOR_REPORT_FILE = "visual_director_report.csv"
COLLECTION_REPORT_FILE = "broll_collection_report.md"
BROLL_DIR = Path("assets") / "broll"

VISUAL_MODES = {
    "avatar",
    "broll",
    "fullscreen_image",
    "split_screen",
    "graphic_explainer",
    "text_callout",
    "document_style",
    "simple_motion",
    "avatar_plus_overlay",
}

SCENE_INTENTS = {
    "hook",
    "explanation",
    "evidence",
    "lifestyle",
    "routine",
    "exercise",
    "medical",
    "symptom",
    "comparison",
    "story",
    "warning",
    "transition",
    "recap",
    "conclusion",
    "CTA",
}

MANIFEST_COLUMNS = [
    "asset_id",
    "scene_id",
    "source",
    "search_query",
    "local_path",
    "original_url",
    "license",
    "creator",
    "duration",
    "resolution",
    "status",
    "notes",
    "scene_intent",
    "recommended_visual_mode",
    "search_query_used",
    "relevance_score",
    "match_status",
    "source_page_url",
    "download_url",
    "license_note",
    "width",
    "height",
    "duplicate_hash",
    "manual_review_required",
    "source_asset_id",
    "semantic_score",
    "hard_match_pass",
    "vision_validation_status",
    "vision_validation_note",
    "vision_subject_score",
    "vision_action_score",
    "vision_setting_score",
    "vision_support_score",
    "vision_safety_score",
    "vision_best_frame_score",
    "vision_average_frame_score",
    "vision_decision",
    "vision_rejection_reason",
    "vision_raw_response_excerpt",
    "vision_parse_status",
    "vision_parse_error",
    "vision_repair_attempted",
    "vision_repair_success",
    "duplicate_status",
    "selected_for_scene",
    "validation_note",
    "best_rejected_asset_id",
    "best_rejected_url",
    "best_rejected_semantic_score",
    "best_rejected_vision_score",
    "best_rejected_stage",
    "best_rejected_reason",
]

CANDIDATE_DIAGNOSTIC_COLUMNS = [
    "scene_id",
    "query_level",
    "search_query",
    "provider",
    "candidate_asset_id",
    "candidate_title",
    "candidate_url",
    "basic_filter_pass",
    "semantic_score",
    "semantic_status",
    "subject_match_score",
    "action_match_score",
    "setting_match_score",
    "demographic_match_score",
    "hard_subject_pass",
    "hard_action_pass",
    "hard_match_pass",
    "vision_status",
    "vision_best_frame_score",
    "vision_average_frame_score",
    "vision_decision",
    "vision_raw_response_excerpt",
    "vision_parse_status",
    "vision_parse_error",
    "vision_repair_attempted",
    "vision_repair_success",
    "duplicate_status",
    "final_candidate_status",
    "rejection_stage",
    "rejection_reason",
    "provider_returned_count",
    "basic_filter_pass_count",
    "semantic_pass_count",
    "hard_match_pass_count",
    "vision_pass_count",
    "duplicate_pass_count",
    "selectable_count",
]

VISUAL_DIRECTOR_COLUMNS = [
    "scene_id",
    "narration_excerpt",
    "original_visual_mode",
    "recommended_visual_mode",
    "scene_intent",
    "viewer_emotion",
    "story_function",
    "medical_context",
    "recommended_shot",
    "subject",
    "action",
    "setting",
    "mood",
    "primary_search",
    "alternative_search_1",
    "alternative_search_2",
    "alternative_search_3",
    "selected_source",
    "selected_asset_url",
    "local_file",
    "candidate_count",
    "selected_asset_id",
    "selected_asset_title",
    "selected_asset_tags",
    "subject_match_score",
    "action_match_score",
    "setting_match_score",
    "demographic_match_score",
    "shot_match_score",
    "narration_relevance_score",
    "medical_safety_score",
    "total_relevance_score",
    "relevance_score",
    "match_status",
    "hard_match_pass",
    "vision_validation_status",
    "vision_validation_note",
    "vision_subject_score",
    "vision_action_score",
    "vision_setting_score",
    "vision_support_score",
    "vision_safety_score",
    "vision_best_frame_score",
    "vision_average_frame_score",
    "vision_decision",
    "vision_rejection_reason",
    "vision_raw_response_excerpt",
    "vision_parse_status",
    "vision_parse_error",
    "vision_repair_attempted",
    "vision_repair_success",
    "duplicate_status",
    "duplicate_of_scene",
    "duplicate_reason",
    "selection_reason",
    "sequence_id",
    "sequence_position",
    "continuity_note",
    "fallback_recommendation",
    "rejection_reason",
    "manual_review_required",
]

DEFAULT_CONFIG = {
    "min_relevance_score": 70,
    "allow_weak_matches": False,
    "max_downloads_per_scene": 1,
    "repetition_window": 8,
    "max_same_action_in_window": 2,
    "max_same_shot_consecutive": 3,
    "prefer_vertical_source": False,
    "preferred_orientation": "landscape",
    "enable_visual_mode_override": True,
    "dry_run": True,
    "min_semantic_score": 75,
    "require_subject_match": True,
    "require_action_match": True,
    "prevent_duplicate_assets": True,
    "detect_near_duplicates": True,
    "candidate_pool_size": 15,
    "fast_download_candidate_pool_size": 3,
    "max_same_creator_assets": 3,
    "show_top_rejected_candidates": 3,
    "enable_vision_validation": False,
    "vision_validation_model": "gpt-4o-mini",
    "vision_validation_required": False,
    "preview_validation_max_bytes": 5_000_000,
    "vision_pass_threshold": 85,
    "vision_acceptable_threshold": 70,
    "vision_uncertain_threshold": 50,
    "vision_preview_frame_limit": 3,
    "max_vision_candidates_per_query": 3,
    "max_vision_requests_per_scene": 6,
    "fast_max_vision_requests_per_scene": 2,
    "profile_fast_candidate_pool_size": 3,
    "profile_fast_max_vision_requests": 2,
    "scene_time_budget_sec": 60,
    "fast_scene_time_budget_sec": 25,
    "profile_fast_scene_time_budget_sec": 30,
    "enable_vision_cache": True,
    "query_builder_mode": "offline",
    "enable_llm_scene_grouping": False,
    "scene_group_chunk_size": 12,
    "llm_grouping_timeout_sec": 20,
    "enable_clip_validation": False,
    "clip_model": "ViT-L-14",
    "clip_validation_timeout_sec": 20,
    "clip_min_score": 0.28,
    "enable_perceptual_hash": False,
    "perceptual_hash_sample_frames": 5,
    "perceptual_hash_threshold": 8,
    "download_connect_timeout_sec": 10,
    "download_timeout_sec": 90,
    "download_retries": 2,
    "prefer_1080p_download": True,
}

WEAK_MATCH_MIN = 60
GOOD_MATCH_MIN = 75
EXCELLENT_MATCH_MIN = 85
SEMANTIC_WEAK_MATCH_MIN = 60

SENSITIVE_TERMS = [
    "fall",
    "falls",
    "dizzy",
    "dizziness",
    "faint",
    "chest pain",
    "palpitations",
    "shortness of breath",
    "sudden weakness",
    "numbness",
    "speech",
    "facial droop",
    "severe pain",
    "neuropathy",
    "vision",
    "parkinson",
    "osteoporosis",
    "fracture",
    "surgery",
    "walking aid",
]

UNSAFE_VISUAL_TERMS = [
    "frightening fall",
    "falling",
    "injury",
    "hospital bed",
    "emergency",
    "scan",
    "x-ray",
    "lab result",
    "miracle",
    "cure",
    "recovery guaranteed",
    "unsafe balance",
]

STOPWORDS = {
    "the",
    "and",
    "that",
    "this",
    "with",
    "from",
    "your",
    "you",
    "are",
    "for",
    "but",
    "not",
    "can",
    "into",
    "what",
    "when",
    "where",
    "they",
    "their",
    "about",
    "after",
    "than",
    "then",
    "just",
}

ABSTRACT_QUERY_TERMS = {
    "curiosity",
    "motivation",
    "trust",
    "reassurance",
    "confidence",
    "hope",
    "surprise",
    "concern",
    "relief",
    "natural",
    "evidence-first",
    "reassuring",
    "emotional",
    "motivational",
}

USELESS_QUERY_WORDS = {
    "person",
    "people",
    "thing",
    "things",
    "front",
    "body",
    "time",
    "day",
    "life",
    "way",
    "someone",
    "something",
    "anything",
    "everything",
    "scene",
    "moment",
    "part",
    "area",
    "place",
}

CONCRETENESS_SCORES = {
    "chair": 10,
    "armrest": 10,
    "handrail": 10,
    "stair": 10,
    "stairs": 10,
    "counter": 10,
    "sidewalk": 10,
    "pavement": 10,
    "shoes": 9,
    "feet": 9,
    "hands": 9,
    "kitchen": 9,
    "hallway": 9,
    "doorway": 9,
    "television": 9,
    "sofa": 9,
    "tablet": 8,
    "exercise": 8,
    "routine": 8,
    "walking": 8,
    "standing": 8,
    "climbing": 8,
    "stepping": 8,
    "holding": 8,
    "reading": 7,
    "support": 7,
    "balance": 7,
    "home": 7,
    "park": 7,
    "grocery": 7,
    "movement": 6,
    "confidence": 2,
    "independence": 2,
    "risk": 1,
    "reason": 1,
    "system": 1,
    "framework": 1,
}

SHOT_WORDS = {
    "wide",
    "medium",
    "close",
    "closeup",
    "close-up",
    "tracking",
    "macro",
    "overhead",
    "pov",
    "hands",
    "shot",
    "view",
    "side",
    "up",
}


@dataclass
class Scene:
    row: dict[str, str]
    index: int

    @property
    def scene_id(self) -> str:
        return self.row.get("scene_id", "").strip()

    @property
    def narration(self) -> str:
        return self.row.get("script_excerpt", "").strip()

    @property
    def original_visual_mode(self) -> str:
        return normalize_visual_mode(self.row.get("visual_mode", ""))

    @property
    def duration(self) -> str:
        return self.row.get("duration_sec", "").strip()


@dataclass
class ShotPlan:
    recommended_visual_mode: str
    scene_intent: str
    viewer_emotion: str
    story_function: str
    medical_context: str
    recommended_shot: str
    subject: str
    action: str
    setting: str
    mood: str
    searches: list[str]
    sequence_id: str
    sequence_position: str
    continuity_note: str
    fallback_recommendation: str
    filmable: bool = True
    rejection_reason: str = ""
    manual_review_required: str = "NO"


@dataclass
class VideoCandidate:
    source: str
    source_page_url: str
    download_url: str
    license_note: str
    creator: str
    duration: str
    width: int
    height: int
    title_text: str
    query_used: str
    file_size: int = 0
    source_asset_id: str = ""
    tags: str = ""
    description: str = ""
    orientation: str = ""
    preview_image: str = ""
    relevance_score: int = 0
    match_status: str = "REJECT"
    score_notes: str = ""
    duplicate_hash: str = ""
    subject_match_score: int = 0
    action_match_score: int = 0
    setting_match_score: int = 0
    demographic_match_score: int = 0
    shot_match_score: int = 0
    narration_relevance_score: int = 0
    medical_safety_score: int = 0
    hard_match_pass: str = "NO"
    validation_note: str = ""
    duplicate_status: str = "UNIQUE"
    duplicate_of_scene: str = ""
    duplicate_reason: str = ""
    selected_for_scene: str = ""
    rejection_reason: str = ""
    vision_validation_status: str = "NOT_RUN"
    vision_validation_note: str = ""
    vision_subject_score: int = 0
    vision_action_score: int = 0
    vision_setting_score: int = 0
    vision_support_score: int = 0
    vision_safety_score: int = 0
    vision_best_frame_score: int = 0
    vision_average_frame_score: int = 0
    vision_decision: str = ""
    vision_rejection_reason: str = ""
    vision_raw_response_excerpt: str = ""
    vision_parse_status: str = ""
    vision_parse_error: str = ""
    vision_repair_attempted: str = "NO"
    vision_repair_success: str = "NO"
    clip_validation_status: str = "NOT_RUN"
    clip_validation_note: str = ""
    clip_score: float = 0.0
    perceptual_hashes: list[str] = field(default_factory=list)

    @property
    def resolution(self) -> str:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return ""


@dataclass
class CollectionStats:
    total_scenes: int = 0
    searched_scenes: int = 0
    downloaded: int = 0
    dry_run_matches: int = 0
    rejected: int = 0
    fallbacks: int = 0
    manual_review: int = 0
    duplicates_blocked: int = 0
    source_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class PerformanceProfile:
    timings: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def add_time(self, stage: str, elapsed: float) -> None:
        self.timings[stage] = self.timings.get(stage, 0.0) + elapsed

    def increment(self, key: str, amount: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + amount


def performance_profile(config: dict[str, Any]) -> PerformanceProfile | None:
    profile = config.get("_performance_profile")
    return profile if isinstance(profile, PerformanceProfile) else None


def timed_call(config: dict[str, Any], stage: str, fn: Any, *args: Any, **kwargs: Any) -> Any:
    profile = performance_profile(config)
    if not profile:
        return fn(*args, **kwargs)
    started = time.perf_counter()
    try:
        return fn(*args, **kwargs)
    finally:
        profile.add_time(stage, time.perf_counter() - started)


def load_vision_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_vision_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def vision_requirement_hash(plan: ShotPlan, scene: Scene, config: dict[str, Any]) -> str:
    payload = {
        "subject": plan.subject,
        "action": plan.action,
        "setting": plan.setting,
        "medical_context": plan.medical_context,
        "narration": compact_text(scene.narration, 260),
        "model": config.get("vision_validation_model", ""),
        "pass": config.get("vision_pass_threshold"),
        "acceptable": config.get("vision_acceptable_threshold"),
        "uncertain": config.get("vision_uncertain_threshold"),
    }
    return stable_hash(json.dumps(payload, sort_keys=True))


def vision_cache_key(candidate: VideoCandidate, plan: ShotPlan, scene: Scene, config: dict[str, Any], preview_images: list[str]) -> str:
    preview_fingerprint = stable_hash("|".join(preview_images))
    asset_id = candidate.source_asset_id or stable_hash(candidate.source_page_url or candidate.download_url)
    return "|".join([candidate.source.lower(), asset_id, preview_fingerprint, vision_requirement_hash(plan, scene, config)])


def vision_cache_payload(candidate: VideoCandidate) -> dict[str, Any]:
    return {
        "vision_validation_status": candidate.vision_validation_status,
        "vision_validation_note": candidate.vision_validation_note,
        "vision_subject_score": candidate.vision_subject_score,
        "vision_action_score": candidate.vision_action_score,
        "vision_setting_score": candidate.vision_setting_score,
        "vision_support_score": candidate.vision_support_score,
        "vision_safety_score": candidate.vision_safety_score,
        "vision_best_frame_score": candidate.vision_best_frame_score,
        "vision_average_frame_score": candidate.vision_average_frame_score,
        "vision_decision": candidate.vision_decision,
        "vision_rejection_reason": candidate.vision_rejection_reason,
        "vision_raw_response_excerpt": candidate.vision_raw_response_excerpt,
        "vision_parse_status": candidate.vision_parse_status,
        "vision_parse_error": candidate.vision_parse_error,
        "vision_repair_attempted": candidate.vision_repair_attempted,
        "vision_repair_success": candidate.vision_repair_success,
        "rejection_reason": candidate.rejection_reason,
        "match_status": candidate.match_status,
        "hard_match_pass": candidate.hard_match_pass,
    }


def apply_cached_vision(candidate: VideoCandidate, payload: dict[str, Any]) -> VideoCandidate:
    for key, value in payload.items():
        if hasattr(candidate, key):
            setattr(candidate, key, value)
    return candidate


def scene_vision_limit(config: dict[str, Any]) -> int:
    if bool(config.get("_profile_fast", False)):
        return int(config.get("profile_fast_max_vision_requests", 2))
    if bool(config.get("_fast_download", False)):
        return int(config.get("fast_max_vision_requests_per_scene", 2))
    return int(config.get("max_vision_requests_per_scene", 6))


def query_vision_limit(config: dict[str, Any]) -> int:
    if bool(config.get("_profile_fast", False)):
        return int(config.get("profile_fast_max_vision_requests", 2))
    if bool(config.get("_fast_download", False)):
        return int(config.get("fast_max_vision_requests_per_scene", 2))
    return int(config.get("max_vision_candidates_per_query", 3))


def scene_time_budget(config: dict[str, Any]) -> float:
    if bool(config.get("_profile_fast", False)):
        return float(config.get("profile_fast_scene_time_budget_sec", 30))
    if bool(config.get("_fast_download", False)):
        return float(config.get("fast_scene_time_budget_sec", 25))
    return float(config.get("scene_time_budget_sec", 60))


def time_budget_exceeded(config: dict[str, Any]) -> bool:
    started = config.get("_scene_started_at")
    if not started:
        return False
    return (time.perf_counter() - float(started)) >= scene_time_budget(config)


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_api_key(name: str) -> str:
    env_file = read_env_file(ROOT / ".env")
    return os.environ.get(name) or env_file.get(name, "")


def http_json(url: str, headers: dict[str, str] | None = None, retries: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = Request(url, headers=headers or {})
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Request failed after {retries} attempts: {last_error}")


def download_file(url: str, destination: Path, retries: int = 2, connect_timeout: int = 10, download_timeout: int = 90) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = Request(url, headers={"User-Agent": "SeniorHealthAI-VisualDirector/2.0"})
            with urlopen(request, timeout=connect_timeout) as response:
                if getattr(response, "fp", None) and getattr(response.fp, "raw", None):
                    response.fp.raw._sock.settimeout(download_timeout)
                destination.write_bytes(response.read())
            return
        except (HTTPError, URLError, TimeoutError, OSError, AttributeError) as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"Download failed after {retries} attempts: {last_error}")


def download_preview_data_url(url: str, config: dict[str, Any]) -> str:
    if not url:
        return ""
    if url.startswith("data:image/"):
        return url
    if not url.startswith(("http://", "https://")):
        return ""
    request = Request(url, headers={"User-Agent": "SeniorHealthAI-VisualDirector/2.0"})
    max_bytes = int(config.get("preview_validation_max_bytes", 5_000_000))
    with urlopen(request, timeout=30) as response:
        payload = response.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise RuntimeError("preview image exceeds validation size limit")
        content_type = response.headers.get_content_type() if response.headers else "image/jpeg"
    if not content_type.startswith("image/"):
        content_type = "image/jpeg"
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_config() -> dict[str, Any]:
    path = ROOT / CONFIG_FILE
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    data = json.loads(path.read_text(encoding="utf-8"))
    visual_config = data.get("visual_director", {})
    merged = dict(DEFAULT_CONFIG)
    if isinstance(visual_config, dict):
        merged.update(visual_config)
    return merged


def apply_fast_download_config(config: dict[str, Any]) -> dict[str, Any]:
    config["candidate_pool_size"] = int(config.get("fast_download_candidate_pool_size", 3))
    config["max_downloads_per_scene"] = 1
    config["prefer_1080p_download"] = True
    return config


def normalize_visual_mode(value: str) -> str:
    value = (value or "").strip().lower()
    mapping = {
        "avatar_only": "avatar",
        "avatar": "avatar",
        "avatar_with_overlay": "avatar_plus_overlay",
        "b-roll": "broll",
        "b_roll": "broll",
        "broll": "broll",
        "fullscreen": "fullscreen_image",
        "fullscreen_image": "fullscreen_image",
        "split": "split_screen",
        "split_screen": "split_screen",
        "graphic": "graphic_explainer",
        "graphic_explainer": "graphic_explainer",
        "document_explainer": "document_style",
        "document_style": "document_style",
        "simple_motion": "simple_motion",
        "text_callout": "text_callout",
    }
    return mapping.get(value, value or "simple_motion")


def compact_text(text: str, max_chars: int = 180) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def tokens(text: str) -> set[str]:
    raw = re.findall(r"[a-zA-Z][a-zA-Z'-]+", text.lower())
    return {word for word in raw if word not in STOPWORDS and len(word) > 2}


def has_any(text: str, terms: list[str]) -> bool:
    low = text.lower()
    return any(term in low for term in terms)


def classify_scene_intent(scene: Scene) -> str:
    text = f"{scene.narration} {scene.row.get('scene_purpose', '')} {scene.row.get('on_screen_text', '')}".lower()
    purpose = scene.row.get("scene_purpose", "").strip().upper()
    if purpose == "HOOK":
        return "hook"
    if purpose == "CTA":
        return "CTA"
    if purpose == "RECAP":
        return "recap"
    if has_any(text, ["research", "study", "trial", "guideline", "evidence", "shown"]):
        return "evidence"
    warning_terms = [term for term in SENSITIVE_TERMS if term not in {"fall", "falls"}]
    if purpose == "WARNING" or has_any(text, warning_terms):
        return "warning"
    if has_any(text, ["imagine", "picture", "two people", "front steps"]):
        return "story"
    if has_any(text, ["walking", "chair", "step", "stand", "balance", "strength", "movement break"]):
        return "routine"
    if has_any(text, ["but", "instead", "versus", "while", "different", "compare"]):
        return "comparison"
    if purpose == "MECHANISM":
        return "explanation"
    if purpose == "SOLUTION":
        return "exercise"
    if scene.index % 7 == 0:
        return "transition"
    return "lifestyle"


def classify_emotion(scene: Scene, intent: str) -> str:
    text = scene.narration.lower()
    if intent in {"warning", "medical", "symptom"}:
        return "reassurance"
    if intent == "hook":
        return "curiosity"
    if intent == "evidence":
        return "trust"
    if intent in {"recap", "conclusion", "CTA"}:
        return "confidence"
    if has_any(text, ["fear", "worried", "scare", "dizzy", "fall"]):
        return "concern"
    if has_any(text, ["encouraging", "good news", "hope", "can be"]):
        return "hope"
    if has_any(text, ["not quite", "quietly", "hidden", "surprised"]):
        return "surprise"
    return "motivation"


def classify_story_function(intent: str, index: int, total: int) -> str:
    if index <= 5:
        return "introduce"
    if intent in {"warning", "medical", "symptom"}:
        return "caution"
    if intent == "evidence":
        return "reinforce"
    if intent in {"routine", "exercise", "lifestyle"}:
        return "demonstrate"
    if intent == "comparison":
        return "compare"
    if intent in {"recap", "conclusion"} or index >= total - 5:
        return "summarize"
    if intent == "CTA":
        return "payoff"
    if intent == "transition":
        return "transition"
    return "explain"


def classify_medical_context(scene: Scene, intent: str) -> str:
    text = scene.narration.lower()
    if has_any(text, ["stroke", "chest pain", "palpitations", "shortness of breath", "sudden weakness", "fracture"]):
        return "sensitive"
    if intent in {"warning", "medical", "symptom"} or has_any(text, SENSITIVE_TERMS):
        return "moderate"
    if has_any(text, ["balance", "fall risk", "exercise", "strength", "therapy", "guidance"]):
        return "low"
    return "none"


def infer_subject_action_setting(scene: Scene, intent: str) -> tuple[str, str, str]:
    return visual_ideas_for_scene(scene, intent)[0]


def visual_ideas_for_scene(scene: Scene, intent: str) -> list[tuple[str, str, str]]:
    text = f"{scene.narration} {scene.row.get('notes', '')} {scene.row.get('on_screen_text', '')}".lower()
    ideas: list[tuple[str, str, str]] = []

    def add(subject: str, action: str, setting: str) -> None:
        item = (subject, action, setting)
        if item not in ideas:
            ideas.append(item)

    if intent == "evidence":
        if has_any(text, ["home-based", "home exercise", "program", "strength", "balance"]):
            add("older woman", "reading home exercise instruction sheet", "kitchen table")
            add("physical therapist", "demonstrating supported chair exercise", "home visit")
            add("older adult", "following printed strength and balance routine", "living room")
            add("tablet screen", "showing exercise program page without readable text", "kitchen table")
        elif has_any(text, ["guideline", "older adults", "recommend"]):
            add("older adult", "reviewing exercise guidance on tablet", "kitchen table")
            add("health educator", "pointing to simple activity framework", "non-clinical studio")
            add("printed routine sheet", "beside walking shoes and chair", "home")
            add("generic study page", "on tablet without readable text", "desk")
        else:
            add("older adult", "following printed routine", "home")
            add("tablet", "displaying generic study page without readable text", "desk")
            add("exercise handout", "beside sturdy chair", "living room")
            add("neutral research visual", "with non-readable paper and pen", "desk")

    if has_any(text, ["chair", "stand up", "standing from", "sit-to-stand", "couch", "seat", "rise"]):
        chair_setting = "dining room at home" if "dining" in text else "living room at home"
        add("older adult", "standing from dining chair", chair_setting)
        add("senior hands", "pressing chair armrests", "home close up")
        add("older adult knees and feet", "preparing for sit to stand movement", "living room")
        add("senior", "rising from chair side view", "bright home")

    if has_any(text, ["sitting", "television", "tv", "meal", "afternoon", "stillness", "movement break"]):
        add("older adult", "watching television seated for long period", "living room")
        add("senior", "standing up after sitting on sofa", "home")
        add("clock", "beside seated older adult", "living room")
        add("older person", "taking short movement break", "home hallway")

    if has_any(text, ["balance", "steady", "weight shift", "shifting", "counter", "wall", "carpet", "tile", "turn", "reach"]):
        add("older adult", "practicing supported balance beside sturdy chair", "bright living room")
        add("senior", "turning carefully in hallway", "home")
        add("older woman", "stepping from carpet to tile", "home")
        add("older adult feet", "shifting weight near support", "floor close up")

    if has_any(text, ["front steps", "stair", "stairs", "handrail", "rail", "curb"]):
        add("older adult", "climbing one stair using handrail", "home staircase")
        add("senior foot", "stepping onto first stair", "staircase")
        add("older adult", "pausing safely near staircase", "home entryway")
        add("senior hand", "holding stair rail", "staircase close up")

    if has_any(text, ["fear", "confidence", "hesitating", "scare", "cautiously", "avoidance", "worried"]):
        add("older adult", "hesitating at front steps", "home entrance")
        add("senior", "walking cautiously toward doorway", "home hallway")
        add("older adult", "using home stairs with handrail", "home staircase")
        add("person", "practicing step with support", "home")

    if has_any(text, ["walking", "walk", "errand", "outing", "pace", "sidewalk", "path"]):
        add("older man", "walking on quiet neighborhood sidewalk", "morning")
        add("older woman", "walking through park path", "daylight")
        add("senior shoes", "walking on even pavement", "sidewalk close up")
        add("older adult", "entering grocery store during errand", "community setting")

    if intent != "evidence" and has_any(text, ["research", "trial", "study", "studies", "guideline", "evidence", "program"]):
        if has_any(text, ["home-based", "home exercise", "program", "strength", "balance"]):
            add("older woman", "reading home exercise instruction sheet", "kitchen table")
            add("physical therapist", "demonstrating supported chair exercise", "home visit")
            add("older adult", "following printed strength and balance routine", "living room")
            add("tablet screen", "showing exercise program page without readable text", "kitchen table")
        elif has_any(text, ["guideline", "older adults", "recommend"]):
            add("older adult", "reviewing exercise guidance on tablet", "kitchen table")
            add("health educator", "pointing to simple activity framework", "non-clinical studio")
            add("printed routine sheet", "beside walking shoes and chair", "home")
            add("generic study page", "on tablet without readable text", "desk")
        else:
            add("older adult", "following printed routine", "home")
            add("tablet", "displaying generic study page without readable text", "desk")
            add("exercise handout", "beside sturdy chair", "living room")
            add("neutral research visual", "with non-readable paper and pen", "desk")

    if has_any(text, ["dizzy", "pain", "chest", "weakness", "professional", "clinician", "physical therapist"]):
        add("health educator", "explaining safety guidance", "professional non-clinical studio")
        add("older adult", "speaking with physical therapist", "bright clinic room")
        add("senior", "holding support while talking with caregiver", "home")
        add("simple safety checklist", "on tablet without readable text", "desk")

    if intent == "CTA":
        add("health educator", "speaking warmly to camera", "professional non-clinical studio")

    if not ideas:
        add("older adult", "moving through daily routine", "warm home")
        add("senior hands", "holding household object", "home close up")
        add("older adult", "walking from room to room", "home")
        add("quiet home hallway", "ready for daily movement", "warm daylight")

    return ideas


def recommend_shot(intent: str, mode: str, scene: Scene, previous_shots: list[str]) -> str:
    text = scene.narration.lower()
    if mode in {"avatar", "avatar_plus_overlay"}:
        return "medium"
    if mode in {"graphic_explainer", "document_style", "text_callout"}:
        return "overhead" if "research" in text or "guideline" in text else "object_detail"
    if has_any(text, ["hands", "hold", "rail", "counter", "chair arm"]):
        shot = "hands"
    elif has_any(text, ["walking", "path", "neighborhood"]):
        shot = "tracking"
    elif has_any(text, ["chair", "stand", "balance", "step"]):
        shot = "medium"
    elif intent in {"transition", "lifestyle"}:
        shot = "wide"
    else:
        shot = "close_up"
    if len(previous_shots) >= 3 and all(item == shot for item in previous_shots[-3:]):
        rotation = ["wide", "medium", "close_up", "hands", "object_detail", "environmental"]
        return next((item for item in rotation if item != shot), "medium")
    return shot


def decide_visual_mode(scene: Scene, intent: str, story_function: str, medical_context: str, config: dict[str, Any]) -> str:
    original = scene.original_visual_mode
    if not config.get("enable_visual_mode_override", True):
        return original
    text = scene.narration.lower()
    if intent == "CTA":
        return "avatar"
    if medical_context == "sensitive":
        return "avatar_plus_overlay"
    if intent == "warning":
        return "avatar_plus_overlay" if has_any(text, ["please", "ask", "guidance"]) else "graphic_explainer"
    if intent == "evidence":
        if has_any(text, ["home-based", "home exercise", "program", "strength", "balance", "delivered", "older women"]):
            return "broll"
        if has_any(text, ["guideline", "marker", "summary", "framework"]):
            return "graphic_explainer"
        return "document_style"
    if intent == "comparison" or has_any(text, ["three parts", "not one", "walking plus", "versus"]):
        return "split_screen"
    if has_any(text, ["system", "strength reserve", "five simple parts", "marker", "framework"]):
        return "graphic_explainer"
    if intent == "hook" and scene.index <= 4:
        return "fullscreen_image"
    if intent in {"routine", "exercise", "lifestyle", "story", "transition"}:
        return "broll"
    if original in VISUAL_MODES:
        return original
    return "simple_motion"


def filmable_scene_detection(scene: Scene, intent: str, medical_context: str) -> tuple[bool, str]:
    text = f"{scene.narration} {scene.row.get('notes', '')} {scene.row.get('on_screen_text', '')}".lower()
    if medical_context == "sensitive":
        return False, "Sensitive medical context is better handled by avatar or graphics."
    if intent in {"CTA", "recap", "conclusion"}:
        return False, f"{intent} scene is primarily presenter-led or synthetic."
    if has_any(text, ["framework", "marker", "mechanism", "system", "research says", "guideline", "meta-analysis", "systematic review"]):
        if not has_any(text, ["walking", "chair", "stair", "handrail", "balance", "exercise", "home program", "printed routine"]):
            return False, "Abstract evidence or framework scene is not a strong stock-footage target."
    if concrete_text_score(text) < 8 and not has_any(text, ["older adult", "senior", "walking", "chair", "home", "stairs", "balance"]):
        return False, "Scene lacks a concrete subject, action, or setting for reliable stock search."
    return True, "Scene has a concrete filmable subject/action/setting."


def fallback_mode_for_unfilmable(intent: str, medical_context: str) -> str:
    if medical_context in {"moderate", "sensitive"} or intent in {"hook", "CTA", "conclusion"}:
        return "avatar_plus_overlay" if intent != "CTA" else "avatar"
    if intent in {"evidence", "explanation", "comparison", "recap"}:
        return "graphic_explainer"
    return "fullscreen_image"


def make_queries(
    subject: str,
    action: str,
    setting: str,
    shot: str,
    mood: str = "",
    scene: Scene | None = None,
    intent: str = "",
    config: dict[str, Any] | None = None,
) -> list[str]:
    return build_queries(subject, action, setting, shot, mood, scene, intent, config or DEFAULT_CONFIG)


def build_queries(
    subject: str,
    action: str,
    setting: str,
    shot: str,
    mood: str,
    scene: Scene | None,
    intent: str,
    config: dict[str, Any],
) -> list[str]:
    mode = str(config.get("query_builder_mode", "offline")).lower()
    if mode == "llm":
        queries = build_queries_llm(subject, action, setting, shot, mood, scene, intent, config)
        if queries:
            return queries
    return build_queries_offline(subject, action, setting, shot, mood, scene, intent)


def build_queries_llm(
    subject: str,
    action: str,
    setting: str,
    shot: str,
    mood: str,
    scene: Scene | None,
    intent: str,
    config: dict[str, Any],
) -> list[str]:
    if not get_api_key("OPENAI_API_KEY"):
        return []
    prompt = {
        "subject": subject,
        "action": action,
        "setting": setting,
        "shot": shot,
        "mood": mood,
        "intent": intent,
        "narration": compact_text(scene.narration, 300) if scene else "",
    }
    result = call_query_builder_model(prompt, config)
    if not isinstance(result, list):
        return []
    queries: list[str] = []
    for item in result:
        query = clean_search_query(str(item), max_words=12)
        if query and normalize_query(query) not in {normalize_query(existing) for existing in queries}:
            queries.append(query)
    return queries[:4] if len(queries) >= 2 else []


def call_query_builder_model(prompt: dict[str, str], config: dict[str, Any]) -> list[str]:
    # Optional hook for future LLM query generation. Offline mode remains the default path.
    return []


def build_queries_offline(
    subject: str,
    action: str,
    setting: str,
    shot: str,
    mood: str = "",
    scene: Scene | None = None,
    intent: str = "",
) -> list[str]:
    ideas = visual_ideas_for_scene(scene, intent) if scene else [(subject, action, setting)]
    while len(ideas) < 4:
        ideas.append(("older adult", supporting_detail_query(subject, action, setting), "home"))
    primary = ideas[0]
    alt_1 = ideas[1]
    alt_2 = ideas[2]
    alt_3 = ideas[3]
    rich = clean_search_query(f"{primary[0]} {primary[1]} {primary[2]}", max_words=10)
    medium = clean_search_query(f"{primary[0]} {primary[1]}", max_words=7)
    short = short_fallback_query(primary[0], primary[1], primary[2])
    supporting = clean_search_query(f"{alt_1[0]} {alt_1[1]} {alt_1[2]}", max_words=9)
    detail = clean_search_query(f"{alt_2[0]} {alt_2[1]} {alt_2[2]}", max_words=9)
    extra = clean_search_query(f"{alt_3[0]} {alt_3[1]} {alt_3[2]}", max_words=9)
    queries = []
    for query in [rich, medium, short, supporting, detail, extra]:
        if query and normalize_query(query) not in {normalize_query(existing) for existing in queries}:
            queries.append(query)
    while len(queries) < 6:
        fallback = semantic_fallback_query(subject, action, setting, len(queries))
        if normalize_query(fallback) not in {normalize_query(existing) for existing in queries}:
            queries.append(fallback)
        else:
            queries.append(f"older adult daily routine home detail {len(queries) + 1}")
    return queries[:6]


def short_fallback_query(subject: str, action: str, setting: str) -> str:
    words = [word for word in clean_search_query(f"{action} {setting} {subject}", max_words=12).split() if CONCRETENESS_SCORES.get(word, 0) >= 7]
    if not words:
        words = clean_search_query(supporting_detail_query(subject, action, setting), max_words=5).split()
    compact = " ".join(words[:4])
    return compact or "older adult movement"


def concrete_text_score(text: str) -> int:
    words = tokens(text)
    return sum(CONCRETENESS_SCORES.get(word, 0) for word in words)


def visual_idea_concreteness(idea: tuple[str, str, str]) -> int:
    subject, action, setting = idea
    return concrete_text_score(f"{subject} {action} {setting}")


def rank_visual_ideas_by_concreteness(ideas: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    ranked = sorted(enumerate(ideas), key=lambda item: (visual_idea_concreteness(item[1]), -item[0]), reverse=True)
    return [idea for _, idea in ranked]


def clean_search_query(text: str, max_words: int = 12, max_chars: int = 110) -> str:
    text = re.sub(r"\b(cinematic|dramatic|ultra|hyperreal|8k|guaranteed|cure|prevent falls)\b", "", text, flags=re.I)
    text = re.sub(r"[^a-zA-Z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    words = [word for word in text.split() if word not in ABSTRACT_QUERY_TERMS and word not in USELESS_QUERY_WORDS]
    if not words:
        return "older adult daily movement home"
    return " ".join(words[:max_words])[:max_chars].strip()


def supporting_detail_query(subject: str, action: str, setting: str) -> str:
    text = f"{action} {setting}".lower()
    if "chair" in text:
        return "senior hands pushing from chair armrest"
    if "balance" in text or "counter" in text:
        return "older adult hand near kitchen counter support"
    if "walking" in text:
        return "senior walking shoes on quiet path"
    if "sitting" in text:
        return "senior standing up from living room chair"
    if "documents" in subject:
        return "older adult reading exercise instruction sheet"
    return "older adult daily routine at home"


def semantic_fallback_query(subject: str, action: str, setting: str, index: int) -> str:
    options = [
        f"{subject} preparing for {action} {setting}",
        f"hands and feet during {action} {setting}",
        f"object detail supporting {action} {setting}",
        f"environment around {action} {setting}",
    ]
    return clean_search_query(options[index % len(options)], max_words=9)


def normalize_query(query: str) -> str:
    query = clean_search_query(query, max_words=50, max_chars=240)
    words = [word for word in query.split() if word not in SHOT_WORDS]
    return " ".join(words)


def base_query_key(query: str) -> str:
    words = normalize_query(query).split()
    return " ".join(words[:6])


def query_category(query: str) -> str:
    low = normalize_query(query)
    if has_any(low, ["walking", "walk", "sidewalk", "path", "pavement", "grocery store"]):
        return "walking"
    if has_any(low, ["document", "documents", "study", "research", "paper", "tablet", "handout", "instruction sheet", "routine sheet"]):
        return "document"
    if has_any(low, ["chair", "armrest", "sit to stand", "standing from", "rising from"]):
        return "chair"
    if has_any(low, ["stair", "handrail", "rail", "step"]):
        return "stairs"
    if has_any(low, ["balance", "weight", "counter", "carpet", "tile"]):
        return "balance"
    if has_any(low, ["sitting", "television", "sofa", "movement break"]):
        return "sitting"
    return "other"


def alternatives_are_semantically_diverse(queries: list[str]) -> bool:
    keys = {base_query_key(query) for query in queries}
    categories = {query_category(query) for query in queries}
    return len(keys) >= min(3, len(queries)) and len(categories) >= 2


def category_limit(category: str, window: int) -> int:
    if category == "walking":
        return max(1, int(window * 0.20 + 0.999))
    if category == "document":
        return max(1, int(window * 0.10 + 0.999))
    if category == "chair":
        return max(1, int(window * 0.15 + 0.999))
    return window


def category_over_limit(category: str, used: dict[str, list[str]], config: dict[str, Any]) -> bool:
    window = int(config.get("repetition_window", 8))
    recent = used.setdefault("categories", [])[-window:]
    return recent.count(category) >= category_limit(category, window)


def select_diverse_primary(queries: list[str], used: dict[str, list[str]], config: dict[str, Any]) -> list[str]:
    normalized_seen = set(used.setdefault("normalized_queries", []))
    recent_base = used.setdefault("base_queries", [])[-int(config.get("repetition_window", 8)) :]
    selected_index = 0
    for index, query in enumerate(queries):
        normalized = normalize_query(query)
        base = base_query_key(query)
        category = query_category(query)
        if normalized in normalized_seen:
            continue
        if recent_base.count(base) >= 2:
            continue
        if category_over_limit(category, used, config):
            continue
        selected_index = index
        break
    reordered = [queries[selected_index]] + [query for i, query in enumerate(queries) if i != selected_index]
    result: list[str] = []
    for query in reordered:
        normalized = normalize_query(query)
        if normalized not in {normalize_query(existing) for existing in result}:
            result.append(query)
    while len(result) < 4:
        fallback = semantic_fallback_query("older adult", "daily movement", "home", len(result))
        if normalize_query(fallback) not in {normalize_query(existing) for existing in result}:
            result.append(fallback)
        else:
            result.append(f"older adult home movement detail {len(result) + 1}")
    return result[:4]


def fallback_for_mode(mode: str, medical_context: str) -> str:
    if mode in {"avatar", "avatar_plus_overlay"}:
        return "AVATAR_RECOMMENDED"
    if mode in {"graphic_explainer", "document_style", "text_callout"}:
        return "GRAPHIC_RECOMMENDED"
    if mode in {"fullscreen_image", "split_screen", "simple_motion"}:
        return "AI_IMAGE_RECOMMENDED"
    if medical_context in {"moderate", "sensitive"}:
        return "AVATAR_RECOMMENDED"
    return "MANUAL_SEARCH_REQUIRED"


def visual_group_key(scene: Scene) -> str:
    intent = classify_scene_intent(scene)
    subject, action, setting = infer_subject_action_setting(scene, intent)
    return base_query_key(clean_search_query(f"{subject} {action} {setting}", max_words=8))


def call_scene_grouping_model(chunk: list[Scene], config: dict[str, Any]) -> list[list[str]]:
    # Optional hook for bounded LLM grouping. Invalid or unavailable results fall back deterministically.
    return []


def validate_scene_groups(groups: list[list[str]], chunk: list[Scene]) -> list[list[str]]:
    expected = [scene.scene_id for scene in chunk]
    seen = [scene_id for group in groups for scene_id in group]
    if seen != expected:
        return []
    if any(not group for group in groups):
        return []
    return groups


def offline_neighbor_scene_groups(chunk: list[Scene]) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    current_key = ""
    for scene in chunk:
        key = visual_group_key(scene)
        if current and key != current_key:
            groups.append(current)
            current = []
        current.append(scene.scene_id)
        current_key = key
    if current:
        groups.append(current)
    return groups


def scene_groups_for_chunk(chunk: list[Scene], config: dict[str, Any]) -> list[list[str]]:
    if bool(config.get("enable_llm_scene_grouping", False)) and get_api_key("OPENAI_API_KEY"):
        groups = validate_scene_groups(call_scene_grouping_model(chunk, config), chunk)
        if groups:
            return groups
    return offline_neighbor_scene_groups(chunk)


def build_story_sequences(scenes: list[Scene], config: dict[str, Any] | None = None) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    sequence = 1
    settings = config or {}
    if not bool(settings.get("enable_llm_scene_grouping", False)):
        for start in range(0, len(scenes), 5):
            group = scenes[start : start + 5]
            total = len(group)
            for pos, scene in enumerate(group, start=1):
                result[scene.scene_id] = (f"SEQ-{sequence:03d}", f"{pos}/{total}")
            sequence += 1
        return result
    by_id = {scene.scene_id: scene for scene in scenes}
    chunk_size = max(2, int(settings.get("scene_group_chunk_size", 12)))
    for start in range(0, len(scenes), chunk_size):
        chunk = scenes[start : start + chunk_size]
        for group_ids in scene_groups_for_chunk(chunk, settings):
            total = len(group_ids)
            for pos, scene_id in enumerate(group_ids, start=1):
                if scene_id in by_id:
                    result[scene_id] = (f"SEQ-{sequence:03d}", f"{pos}/{total}")
            sequence += 1
    for scene in scenes:
        if scene.scene_id not in result:
            result[scene.scene_id] = (f"SEQ-{sequence:03d}", "1/1")
            sequence += 1
    return result


def plan_scene(scene: Scene, total: int, config: dict[str, Any], previous_shots: list[str], sequence_info: tuple[str, str]) -> ShotPlan:
    intent = classify_scene_intent(scene)
    emotion = classify_emotion(scene, intent)
    story_function = classify_story_function(intent, scene.index, total)
    medical_context = classify_medical_context(scene, intent)
    filmable, filmable_reason = filmable_scene_detection(scene, intent, medical_context)
    mode = decide_visual_mode(scene, intent, story_function, medical_context, config)
    if not filmable and mode == "broll":
        mode = fallback_mode_for_unfilmable(intent, medical_context)
    subject, action, setting = infer_subject_action_setting(scene, intent)
    mood = "calm and reassuring" if medical_context in {"moderate", "sensitive"} else f"{emotion} and natural"
    shot = recommend_shot(intent, mode, scene, previous_shots)
    searches = make_queries(subject, action, setting, shot, mood, scene=scene, intent=intent, config=config)
    sequence_id, sequence_position = sequence_info
    continuity_note = continuity_for_position(sequence_position, mode, shot)
    fallback = fallback_for_mode(mode, medical_context)
    manual_review = "YES" if medical_context in {"moderate", "sensitive"} or mode != "broll" else "NO"
    rejection_reason = "" if mode == "broll" else (filmable_reason if not filmable else f"Stock footage not primary treatment for {mode} scene.")
    return ShotPlan(
        recommended_visual_mode=mode,
        scene_intent=intent,
        viewer_emotion=emotion,
        story_function=story_function,
        medical_context=medical_context,
        recommended_shot=shot,
        subject=subject,
        action=action,
        setting=setting,
        mood=mood,
        searches=searches,
        sequence_id=sequence_id,
        sequence_position=sequence_position,
        continuity_note=continuity_note,
        fallback_recommendation=fallback,
        filmable=filmable,
        rejection_reason=rejection_reason,
        manual_review_required=manual_review,
    )


def continuity_for_position(sequence_position: str, mode: str, shot: str) -> str:
    pos = int(sequence_position.split("/", 1)[0])
    if pos == 1:
        return f"Open the sequence with a clear {shot} setup before moving into detail."
    if pos in {2, 3}:
        return f"Continue visual progression with {mode}; avoid repeating the prior shot composition."
    if pos == 4:
        return "Use a detail, reflective, or explanatory beat to reset attention."
    return "Resolve the sequence and transition cleanly toward the next idea or avatar."


def parse_production(project: Path) -> list[Scene]:
    path = project / PRODUCTION_FILE
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [Scene(row=row, index=index) for index, row in enumerate(rows, start=1)]


def require_input_files(project: Path) -> None:
    for filename in [PRODUCTION_FILE, IMAGE_PROMPTS_FILE, BROLL_PROMPTS_FILE]:
        path = project / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing {path}")
    root_config = ROOT / CONFIG_FILE
    if not root_config.exists():
        raise FileNotFoundError(f"Missing {root_config}")


def candidate_text(candidate: VideoCandidate) -> str:
    return " ".join(
        value
        for value in [
            candidate.title_text,
            candidate.tags,
            candidate.description,
            candidate.creator,
            candidate.source_page_url,
            candidate.query_used,
        ]
        if value
    ).lower()


def match_profile(plan: ShotPlan, scene: Scene) -> dict[str, Any]:
    text = f"{plan.subject} {plan.action} {plan.setting} {scene.narration} {' '.join(plan.searches)}".lower()
    if has_any(text, ["chair", "armrest", "sit to stand", "standing from", "rising from"]):
        return {
            "name": "chair_rise",
            "subject_terms": ["senior", "older", "elderly", "adult", "woman", "man", "person"],
            "required_age_terms": ["senior", "older", "elderly", "old"],
            "action_terms": ["chair", "sitting", "standing", "stand", "rising", "armrest", "sit to stand"],
            "setting_terms": ["home", "living", "dining", "room", "chair"],
            "contradictions": ["easter", "celebration", "party", "cards", "poker", "trees", "forest", "empty path"],
            "human_required": True,
        }
    if has_any(text, ["printed routine", "instruction sheet", "exercise program", "guidance", "handout", "tablet"]):
        return {
            "name": "printed_routine",
            "subject_terms": ["senior", "older", "elderly", "adult", "woman", "man", "person"],
            "required_age_terms": ["senior", "older", "elderly", "old"],
            "action_terms": ["reading", "following", "instruction", "routine", "exercise", "program", "handout", "tablet", "paper"],
            "setting_terms": ["home", "kitchen", "table", "living", "room"],
            "contradictions": ["cards", "poker", "game", "easter", "celebration", "party"],
            "human_required": True,
        }
    if has_any(text, ["walking", "walk", "sidewalk", "path", "pavement"]):
        return {
            "name": "walking",
            "subject_terms": ["senior", "older", "elderly", "adult", "woman", "man", "person"],
            "required_age_terms": ["senior", "older", "elderly", "old"],
            "action_terms": ["walking", "walk", "strolling", "sidewalk", "path"],
            "setting_terms": ["sidewalk", "path", "neighborhood", "park", "pavement", "street"],
            "contradictions": ["trees", "forest", "empty", "landscape", "pathway no people", "road no people"],
            "human_required": True,
        }
    if has_any(text, ["stair", "step", "handrail", "rail"]):
        return {
            "name": "stairs",
            "subject_terms": ["senior", "older", "elderly", "adult", "woman", "man", "person"],
            "required_age_terms": ["senior", "older", "elderly", "old"],
            "action_terms": ["stair", "stairs", "step", "handrail", "rail", "climbing"],
            "setting_terms": ["staircase", "stairs", "home", "entryway"],
            "contradictions": ["ladder", "construction", "child", "running"],
            "human_required": True,
        }
    if has_any(text, ["balance", "weight", "carpet", "tile", "counter", "support"]):
        return {
            "name": "balance",
            "subject_terms": ["senior", "older", "elderly", "adult", "woman", "man", "person"],
            "required_age_terms": ["senior", "older", "elderly", "old"],
            "action_terms": ["balance", "standing", "support", "counter", "chair", "weight", "stepping", "tile", "carpet"],
            "setting_terms": ["home", "living", "kitchen", "hallway", "floor"],
            "contradictions": ["yoga pose", "athlete", "gymnast", "running"],
            "human_required": True,
        }
    if has_any(text, ["sitting", "television", "seated", "sofa", "movement break"]):
        return {
            "name": "long_sitting",
            "subject_terms": ["senior", "older", "elderly", "adult", "woman", "man", "person"],
            "required_age_terms": ["senior", "older", "elderly", "old"],
            "action_terms": ["sitting", "seated", "television", "sofa", "chair", "standing", "movement"],
            "setting_terms": ["home", "living", "room", "sofa"],
            "contradictions": ["party", "cards", "running", "gym"],
            "human_required": True,
        }
    return {
        "name": "general",
        "subject_terms": tokens(plan.subject),
        "required_age_terms": [],
        "action_terms": tokens(plan.action),
        "setting_terms": tokens(plan.setting),
        "contradictions": [],
        "human_required": False,
    }


def term_match(text: str, terms: Any) -> bool:
    return any(str(term).lower() in text for term in terms if str(term).strip())


def score_terms(text: str, terms: Any, max_points: int) -> int:
    terms_list = [str(term).lower() for term in terms if str(term).strip()]
    if not terms_list:
        return max_points
    matches = sum(1 for term in terms_list if term in text)
    return min(max_points, int(round((matches / max(1, min(3, len(terms_list)))) * max_points)))


def validate_candidate_semantics(candidate: VideoCandidate, plan: ShotPlan, scene: Scene, config: dict[str, Any]) -> VideoCandidate:
    text = candidate_text(candidate)
    profile = match_profile(plan, scene)
    subject_ok = term_match(text, profile["subject_terms"])
    age_ok = not profile["required_age_terms"] or term_match(text, profile["required_age_terms"])
    action_ok = term_match(text, profile["action_terms"])
    setting_ok = term_match(text, profile["setting_terms"])
    contradiction = term_match(text, profile["contradictions"])
    background_only = profile["human_required"] and has_any(text, ["trees", "forest", "landscape", "empty path", "no people", "background"])

    candidate.subject_match_score = 25 if subject_ok and (age_ok or not profile["required_age_terms"]) else (12 if subject_ok else 0)
    candidate.action_match_score = 25 if action_ok else 0
    candidate.setting_match_score = score_terms(text, profile["setting_terms"], 15)
    candidate.demographic_match_score = 10 if age_ok else (5 if subject_ok and not profile["required_age_terms"] else 0)
    candidate.shot_match_score = 10 if plan.recommended_shot in text or orientation_suits_shot(candidate, plan.recommended_shot) else 5
    candidate.narration_relevance_score = min(10, len((tokens(text) & tokens(scene.narration))) * 2)
    candidate.medical_safety_score = 0 if contradiction or has_any(text, UNSAFE_VISUAL_TERMS) else 5
    hard_subject = subject_ok and (age_ok or not profile["required_age_terms"])
    hard_action = action_ok
    if not bool(config.get("require_subject_match", True)):
        hard_subject = True
    if not bool(config.get("require_action_match", True)):
        hard_action = True
    candidate.hard_match_pass = "YES" if hard_subject and hard_action and not contradiction and not background_only else "NO"
    total = (
        candidate.subject_match_score
        + candidate.action_match_score
        + candidate.setting_match_score
        + candidate.demographic_match_score
        + candidate.shot_match_score
        + candidate.narration_relevance_score
        + candidate.medical_safety_score
    )
    candidate.relevance_score = max(0, min(100, int(total)))
    if candidate.hard_match_pass != "YES":
        reasons: list[str] = []
        if not hard_subject:
            reasons.append("required subject missing")
        if not hard_action:
            reasons.append("required action missing")
        if contradiction:
            reasons.append("unrelated or contradictory activity")
        if background_only:
            reasons.append("background-only shot for human-action scene")
        candidate.rejection_reason = "; ".join(reasons)
        candidate.match_status = "REJECT"
    else:
        candidate.match_status = match_status(candidate.relevance_score)
        if candidate.match_status == "REJECT":
            candidate.rejection_reason = "semantic score below threshold"
    candidate.score_notes = (
        f"subject={candidate.subject_match_score}; action={candidate.action_match_score}; "
        f"setting={candidate.setting_match_score}; demographic={candidate.demographic_match_score}; "
        f"shot={candidate.shot_match_score}; narration={candidate.narration_relevance_score}; "
        f"medical={candidate.medical_safety_score}; hard_match={candidate.hard_match_pass}"
    )
    candidate.validation_note = candidate.rejection_reason or "validated semantic match"
    candidate.duplicate_hash = candidate_hash(candidate)
    return candidate


def vision_prompt(plan: ShotPlan, scene: Scene) -> str:
    return (
        "You are validating a stock-video preview image for a senior-health video. "
        "Use weighted scoring for the visible preview frame. Return one JSON object only. "
        "No markdown fences. No commentary. Use exact field names. "
        "All scores must be integers from 0 to 100. "
        "decision must be one of VISION_PASS, VISION_ACCEPTABLE, VISION_UNCERTAIN, "
        "VISION_FAIL, PREVIEW_UNAVAILABLE, ERROR. "
        "Answer only JSON with keys: "
        "older_adult_visible, stairs_or_step_visible, stepping_action_visible, "
        "handrail_or_support_visible, home_or_interior_visible, medical_safety_ok, "
        "contradicts_narration, unrelated_activity, unsafe_or_misleading, "
        "subject_score, action_score, setting_score, support_score, safety_score, "
        "best_frame_score, average_frame_score, decision, rejection_reason, note. "
        "The score weights are older adult 25, stairs or step 20, stepping action 25, "
        "handrail or support 15, home or interior setting 10, medical safety 5. "
        "Do not require every requested detail to be visible if the preview clearly matches "
        "the stock-video concept. Strictly reject no older adult, no stairs or steps for a "
        "stairs scene, contradictory action, unrelated activity, or unsafe misleading footage. "
        f"Expected subject: {plan.subject}. Expected action: {plan.action}. "
        f"Expected setting: {plan.setting}. Medical context: {plan.medical_context}. "
        f"Narration: {compact_text(scene.narration, 260)}"
    )


ALLOWED_VISION_DECISIONS = {
    "VISION_PASS",
    "VISION_ACCEPTABLE",
    "VISION_UNCERTAIN",
    "VISION_FAIL",
    "PREVIEW_UNAVAILABLE",
    "ERROR",
}


def response_excerpt(text: str, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def strip_markdown_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    fenced = re.match(r"^```(?:json|JSON)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    return fenced.group(1).strip() if fenced else stripped


def first_balanced_json(text: str, opener: str, closer: str) -> str:
    start = text.find(opener)
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        start = text.find(opener, start + 1)
    return ""


def coerce_vision_score(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return 100 if value else 0
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        if not match:
            return default
        number = float(match.group(0))
    return max(0, min(100, int(round(number))))


def normalize_vision_decision(value: Any, best_score: int | None = None) -> str:
    if value is None or str(value).strip() == "":
        if best_score is None:
            return ""
        return vision_decision_for_score(best_score, DEFAULT_CONFIG)
    decision = str(value).strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "PASS": "VISION_PASS",
        "PASSED": "VISION_PASS",
        "ACCEPTABLE": "VISION_ACCEPTABLE",
        "UNCERTAIN": "VISION_UNCERTAIN",
        "FAIL": "VISION_FAIL",
        "FAILED": "VISION_FAIL",
        "PREVIEW_MISSING": "PREVIEW_UNAVAILABLE",
        "NO_PREVIEW": "PREVIEW_UNAVAILABLE",
    }
    decision = aliases.get(decision, decision)
    return decision if decision in ALLOWED_VISION_DECISIONS else ""


def decode_json_candidate(text: str) -> tuple[Any | None, str]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, str(exc)
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError as exc:
            return None, str(exc)
    if isinstance(parsed, list):
        if len(parsed) == 1 and isinstance(parsed[0], dict):
            return parsed[0], ""
        return None, "vision response array did not contain exactly one object"
    if isinstance(parsed, dict):
        return parsed, ""
    return None, "vision response was not an object"


def parse_vision_response_text(response_text: str) -> tuple[dict[str, Any] | None, str, str]:
    attempts = [
        ("direct", response_text.strip()),
        ("code_fence", strip_markdown_code_fence(response_text)),
        ("balanced_object", first_balanced_json(response_text, "{", "}")),
        ("balanced_array", first_balanced_json(response_text, "[", "]")),
    ]
    last_error = "empty vision response"
    for label, candidate_text in attempts:
        if not candidate_text:
            continue
        parsed, error = decode_json_candidate(candidate_text)
        if isinstance(parsed, dict):
            return normalize_vision_payload(parsed), label, ""
        last_error = f"{label}: {error}"
    return None, "FAILED", last_error


def normalize_vision_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    aliases = {
        "vision_decision": "decision",
        "reason": "rejection_reason",
        "overall_score": "best_frame_score",
        "total_score": "best_frame_score",
        "total": "best_frame_score",
        "average_score": "average_frame_score",
        "avg_frame_score": "average_frame_score",
        "medical_safety_score": "safety_score",
        "safety": "safety_score",
        "support_visible": "handrail_or_support_visible",
        "subject_exists": "older_adult_visible",
        "action_exists": "stepping_action_visible",
        "setting_matches": "home_or_interior_visible",
    }
    for source, target in aliases.items():
        if target not in normalized and source in normalized:
            normalized[target] = normalized[source]
    score_fields = [
        "subject_score",
        "action_score",
        "setting_score",
        "support_score",
        "safety_score",
        "best_frame_score",
        "average_frame_score",
    ]
    for field_name in score_fields:
        if field_name in normalized:
            normalized[field_name] = coerce_vision_score(normalized[field_name])
    component_total = sum(
        coerce_vision_score(normalized.get(field_name))
        for field_name in ["subject_score", "action_score", "setting_score", "support_score", "safety_score"]
        if field_name in normalized
    )
    if "best_frame_score" not in normalized and component_total:
        normalized["best_frame_score"] = max(0, min(100, component_total))
    if "average_frame_score" not in normalized and "best_frame_score" in normalized:
        normalized["average_frame_score"] = normalized["best_frame_score"]
    best_score = normalized.get("best_frame_score")
    decision = normalize_vision_decision(normalized.get("decision"), best_score if isinstance(best_score, int) else None)
    if decision:
        normalized["decision"] = decision
        normalized.setdefault("status", vision_status_for_decision(decision) if decision.startswith("VISION_") else decision)
    if "rejection_reason" in normalized and "note" not in normalized:
        normalized["note"] = normalized["rejection_reason"]
    if "subject_score" in normalized:
        normalized.setdefault("older_adult_visible", normalized["subject_score"] > 0)
        normalized.setdefault("subject_exists", normalized["subject_score"] > 0)
        normalized.setdefault("age_group_matches", normalized["subject_score"] > 0)
    if "action_score" in normalized:
        normalized.setdefault("stepping_action_visible", normalized["action_score"] > 0)
        normalized.setdefault("action_exists", normalized["action_score"] > 0)
    if "setting_score" in normalized:
        normalized.setdefault("stairs_or_step_visible", normalized["setting_score"] >= 20)
        normalized.setdefault("home_or_interior_visible", normalized["setting_score"] > 0)
        normalized.setdefault("setting_matches", normalized["setting_score"] > 0)
    if "support_score" in normalized:
        normalized.setdefault("handrail_or_support_visible", normalized["support_score"] > 0)
    if "safety_score" in normalized:
        normalized.setdefault("medical_safety_ok", normalized["safety_score"] > 0)
        normalized.setdefault("medical_context_matches", normalized["safety_score"] > 0)
    return normalized


def request_vision_json_repair(raw_response: str, config: dict[str, Any]) -> tuple[str, str]:
    api_key = get_api_key("OPENAI_API_KEY")
    if not api_key:
        return "", "missing OPENAI_API_KEY for vision repair"
    body = {
        "model": config.get("vision_validation_model", "gpt-4o-mini"),
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Return only valid JSON matching the required schema. No markdown or prose.\n"
                            "Required fields: subject_score, action_score, setting_score, support_score, "
                            "safety_score, best_frame_score, average_frame_score, decision, rejection_reason.\n"
                            "Allowed decision values: VISION_PASS, VISION_ACCEPTABLE, VISION_UNCERTAIN, "
                            "VISION_FAIL, PREVIEW_UNAVAILABLE, ERROR.\n"
                            f"Raw response to repair:\n{response_excerpt(raw_response, 2000)}"
                        ),
                    }
                ],
            }
        ],
    }
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "SeniorHealthAI-VisualDirector/2.0",
        },
        method="POST",
    )
    profile = performance_profile(config)
    if profile:
        profile.increment("vision_requests")
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        if profile:
            profile.add_time("vision_validation", time.perf_counter() - started)
        return "", f"vision repair request unavailable: {exc}"
    if profile:
        profile.add_time("vision_validation", time.perf_counter() - started)
    return extract_response_text(data), ""


def parsed_vision_response(response_text: str, config: dict[str, Any]) -> dict[str, Any]:
    excerpt = response_excerpt(response_text)
    parsed, parse_status, parse_error = parse_vision_response_text(response_text)
    if parsed is not None:
        parsed["_vision_raw_response_excerpt"] = excerpt
        parsed["_vision_parse_status"] = parse_status
        parsed["_vision_parse_error"] = ""
        parsed["_vision_repair_attempted"] = "NO"
        parsed["_vision_repair_success"] = "NO"
        return parsed

    repair_text, repair_request_error = request_vision_json_repair(response_text, config)
    if repair_text:
        repaired, repair_status, repair_error = parse_vision_response_text(repair_text)
        if repaired is not None:
            repaired["_vision_raw_response_excerpt"] = excerpt
            repaired["_vision_parse_status"] = f"REPAIRED:{repair_status}"
            repaired["_vision_parse_error"] = ""
            repaired["_vision_repair_attempted"] = "YES"
            repaired["_vision_repair_success"] = "YES"
            return repaired
        parse_error = repair_error
    elif repair_request_error:
        parse_error = f"{parse_error}; {repair_request_error}"

    return {
        "status": "ERROR",
        "decision": "ERROR",
        "note": "vision response was not parseable JSON",
        "_vision_raw_response_excerpt": excerpt,
        "_vision_parse_status": "FAILED",
        "_vision_parse_error": parse_error,
        "_vision_repair_attempted": "YES",
        "_vision_repair_success": "NO",
    }


def call_vision_model(preview_image: str, prompt: str, config: dict[str, Any]) -> dict[str, Any]:
    api_key = get_api_key("OPENAI_API_KEY")
    if not api_key or not preview_image:
        return {"status": "ERROR", "note": "missing OPENAI_API_KEY or preview image"}
    try:
        image_url = timed_call(config, "preview_download", download_preview_data_url, preview_image, config)
        profile = performance_profile(config)
        if profile:
            profile.increment("preview_downloads")
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
        return {"status": "ERROR", "note": f"preview image unavailable: {exc}"}
    if not image_url:
        return {"status": "ERROR", "note": "preview image unavailable or unsupported"}
    body = {
        "model": config.get("vision_validation_model", "gpt-4o-mini"),
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_url},
                ],
            }
        ],
    }
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "SeniorHealthAI-VisualDirector/2.0",
        },
        method="POST",
    )
    profile = performance_profile(config)
    if profile:
        profile.increment("vision_requests")
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        if profile:
            profile.add_time("vision_validation", time.perf_counter() - started)
        return {"status": "ERROR", "note": f"vision request unavailable: {exc}"}
    if profile:
        profile.add_time("vision_validation", time.perf_counter() - started)
    text = extract_response_text(data)
    return parsed_vision_response(text, config)


def extract_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()
    parts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def apply_vision_parse_diagnostics(candidate: VideoCandidate, result: dict[str, Any]) -> None:
    candidate.vision_raw_response_excerpt = str(result.get("_vision_raw_response_excerpt", ""))
    candidate.vision_parse_status = str(result.get("_vision_parse_status", ""))
    candidate.vision_parse_error = str(result.get("_vision_parse_error", ""))
    candidate.vision_repair_attempted = str(result.get("_vision_repair_attempted", "NO"))
    candidate.vision_repair_success = str(result.get("_vision_repair_success", "NO"))


def is_stair_scene(plan: ShotPlan, scene: Scene) -> bool:
    text = " ".join([plan.action, plan.setting, " ".join(plan.searches[:3]), scene.narration]).lower()
    return has_any(text, ["stair", "stairs", "step", "steps", "handrail", "rail"])


def candidate_preview_images(candidate: VideoCandidate, config: dict[str, Any]) -> list[str]:
    limit = max(1, int(config.get("vision_preview_frame_limit", 3)))
    images: list[str] = []
    raw = candidate.raw if hasattr(candidate, "raw") else {}
    for value in [
        candidate.preview_image,
        raw.get("thumbnail") if isinstance(raw, dict) else "",
        raw.get("thumb") if isinstance(raw, dict) else "",
        raw.get("keyframe") if isinstance(raw, dict) else "",
        raw.get("preview") if isinstance(raw, dict) else "",
        raw.get("preview_image") if isinstance(raw, dict) else "",
        raw.get("image") if isinstance(raw, dict) else "",
        raw.get("poster") if isinstance(raw, dict) else "",
        raw.get("poster_frame") if isinstance(raw, dict) else "",
        raw.get("picture") if isinstance(raw, dict) else "",
        raw.get("picture_id") if isinstance(raw, dict) else "",
    ]:
        if not value:
            continue
        image = str(value).strip()
        if candidate.source.lower() == "pixabay" and image and not image.startswith(("http://", "https://", "data:")):
            image = f"https://i.vimeocdn.com/video/{image}_640x360.jpg"
        if image and image not in images:
            images.append(image)
        if len(images) >= limit:
            break
    return images


def vision_bool(result: dict[str, Any], *names: str) -> bool:
    return any(bool(result.get(name)) for name in names)


def score_vision_frame(result: dict[str, Any], plan: ShotPlan, scene: Scene) -> dict[str, Any]:
    stair_scene = is_stair_scene(plan, scene)
    older_adult_visible = vision_bool(result, "older_adult_visible") or (
        vision_bool(result, "subject_exists") and vision_bool(result, "age_group_matches")
    )
    step_visible = vision_bool(result, "stairs_or_step_visible", "stair_or_step_visible")
    setting_visible = vision_bool(result, "home_or_interior_visible", "setting_matches")
    action_visible = vision_bool(result, "stepping_action_visible", "action_exists")
    support_visible = vision_bool(result, "handrail_or_support_visible", "support_visible")
    safety_ok = not bool(result.get("unsafe_or_misleading")) and (
        result.get("medical_safety_ok") is not False and result.get("medical_context_matches") is not False
    )
    subject_score = 25 if older_adult_visible else 0
    setting_score = (20 if (step_visible or not stair_scene) else 0) + (10 if setting_visible else 0)
    action_score = 25 if action_visible else 0
    support_score = 15 if support_visible else 0
    safety_score = 5 if safety_ok else 0
    total = subject_score + setting_score + action_score + support_score + safety_score
    strict_reasons: list[str] = []
    if not older_adult_visible:
        strict_reasons.append("no older adult visible")
    if stair_scene and not step_visible:
        strict_reasons.append("no stairs or steps visible")
    if bool(result.get("contradicts_narration")):
        strict_reasons.append("action contradicts narration")
    if bool(result.get("unrelated_activity")) or bool(result.get("reject")):
        strict_reasons.append("unrelated activity")
    if not safety_ok:
        strict_reasons.append("unsafe or misleading footage")
    critical_failure = any(
        reason in strict_reasons
        for reason in [
            "no older adult visible",
            "no stairs or steps visible",
            "action contradicts narration",
            "unrelated activity",
            "unsafe or misleading footage",
        ]
    )
    if plan.action and not action_visible:
        total = min(total, 69)
        if total >= 50:
            strict_reasons.append("required action not visible enough")
    if critical_failure:
        total = min(total, 49)
    elif strict_reasons and total >= 70:
        total = 69
    return {
        "subject_score": subject_score,
        "action_score": action_score,
        "setting_score": setting_score,
        "support_score": support_score,
        "safety_score": safety_score,
        "total": total,
        "strict_reasons": strict_reasons,
        "note": str(result.get("note") or ""),
    }


def vision_decision_for_score(score: int, config: dict[str, Any]) -> str:
    if score >= int(config.get("vision_pass_threshold", 85)):
        return "VISION_PASS"
    if score >= int(config.get("vision_acceptable_threshold", 70)):
        return "VISION_ACCEPTABLE"
    if score >= int(config.get("vision_uncertain_threshold", 50)):
        return "VISION_UNCERTAIN"
    return "VISION_FAIL"


def vision_status_for_decision(decision: str) -> str:
    if decision == "VISION_PASS":
        return "PASSED"
    if decision == "VISION_ACCEPTABLE":
        return "ACCEPTABLE"
    if decision == "VISION_UNCERTAIN":
        return "UNCERTAIN"
    return "FAILED"


def apply_vision_scores(candidate: VideoCandidate, frame_scores: list[dict[str, Any]], config: dict[str, Any]) -> VideoCandidate:
    best = max(frame_scores, key=lambda item: int(item["total"]))
    average = int(round(sum(int(item["total"]) for item in frame_scores) / max(1, len(frame_scores))))
    decision = vision_decision_for_score(int(best["total"]), config)
    candidate.vision_subject_score = int(best["subject_score"])
    candidate.vision_action_score = int(best["action_score"])
    candidate.vision_setting_score = int(best["setting_score"])
    candidate.vision_support_score = int(best["support_score"])
    candidate.vision_safety_score = int(best["safety_score"])
    candidate.vision_best_frame_score = int(best["total"])
    candidate.vision_average_frame_score = average
    candidate.vision_decision = decision
    candidate.vision_validation_status = vision_status_for_decision(decision)
    reasons = list(best.get("strict_reasons") or [])
    note = str(best.get("note") or "")
    candidate.vision_rejection_reason = "; ".join(reasons)
    candidate.vision_validation_note = note or decision.lower().replace("_", " ")
    if decision in {"VISION_FAIL", "VISION_UNCERTAIN"}:
        candidate.match_status = "REJECT"
        candidate.hard_match_pass = "NO"
        candidate.rejection_reason = candidate.vision_rejection_reason or candidate.vision_validation_note
    return candidate


def validate_candidate_vision(candidate: VideoCandidate, plan: ShotPlan, scene: Scene, config: dict[str, Any]) -> VideoCandidate:
    if not bool(config.get("enable_vision_validation", False)):
        candidate.vision_validation_status = "DISABLED"
        candidate.vision_validation_note = "vision validation disabled"
        return candidate
    frame_scores: list[dict[str, Any]] = []
    prompt = vision_prompt(plan, scene)
    preview_images = candidate_preview_images(candidate, config)
    if not preview_images:
        candidate.vision_validation_status = "PREVIEW_UNAVAILABLE"
        candidate.vision_decision = "PREVIEW_UNAVAILABLE"
        candidate.vision_validation_note = "no preview image, provider thumbnail, keyframe, or poster frame available"
        candidate.vision_rejection_reason = candidate.vision_validation_note
        candidate.rejection_reason = candidate.vision_validation_note
        return candidate
    cache_key = vision_cache_key(candidate, plan, scene, config, preview_images)
    cache = config.get("_vision_cache") if bool(config.get("enable_vision_cache", True)) else None
    if isinstance(cache, dict) and not bool(config.get("_force_vision_cache_refresh", False)) and cache_key in cache:
        profile = performance_profile(config)
        if profile:
            profile.increment("vision_cache_hits")
        return apply_cached_vision(candidate, cache[cache_key])
    result = {}
    for preview_image in preview_images:
        result = call_vision_model(preview_image, prompt, config)
        apply_vision_parse_diagnostics(candidate, result)
        if result.get("status") in {"ERROR", "UNCERTAIN", "SKIPPED"}:
            if not frame_scores:
                candidate.vision_validation_status = "UNCERTAIN" if result.get("status") == "SKIPPED" else str(result.get("status"))
                candidate.vision_decision = str(result.get("decision") or ("VISION_UNCERTAIN" if candidate.vision_validation_status == "UNCERTAIN" else "ERROR"))
                candidate.vision_validation_note = str(result.get("note", "vision validation unavailable"))
                candidate.vision_rejection_reason = candidate.vision_validation_note
                candidate.match_status = "REJECT"
                candidate.hard_match_pass = "NO"
                candidate.rejection_reason = f"vision validation {candidate.vision_validation_status.lower()}: {candidate.vision_validation_note}"
                return candidate
            continue
        scored = score_vision_frame(result, plan, scene)
        frame_scores.append(scored)
        if vision_decision_for_score(int(scored["total"]), config) == "VISION_PASS":
            break
    if not frame_scores:
        candidate.vision_validation_status = str(result.get("status", "ERROR"))
        candidate.vision_decision = str(result.get("decision") or ("VISION_UNCERTAIN" if candidate.vision_validation_status == "UNCERTAIN" else "ERROR"))
        candidate.vision_validation_note = str(result.get("note", "vision validation unavailable"))
        candidate.vision_rejection_reason = candidate.vision_validation_note
        candidate.match_status = "REJECT"
        candidate.hard_match_pass = "NO"
        candidate.rejection_reason = f"vision validation {candidate.vision_validation_status.lower()}: {candidate.vision_validation_note}"
        return candidate
    candidate = apply_vision_scores(candidate, frame_scores, config)
    if isinstance(cache, dict):
        cache[cache_key] = vision_cache_payload(candidate)
        config["_vision_cache_dirty"] = True
    return candidate


def candidate_preview_passes_before_download(candidate: VideoCandidate, plan: ShotPlan, scene: Scene, config: dict[str, Any]) -> bool:
    if not bool(config.get("enable_vision_validation", False)):
        return True
    if candidate.vision_validation_status not in {"PASSED", "ACCEPTABLE", "FAILED", "ERROR", "UNCERTAIN", "PREVIEW_UNAVAILABLE"}:
        validate_candidate_vision(candidate, plan, scene, config)
    if candidate.vision_validation_status in {"PASSED", "ACCEPTABLE"} and candidate.vision_best_frame_score >= int(config.get("vision_acceptable_threshold", 70)):
        return True
    if candidate_preview_unavailable_review_download(candidate):
        candidate.vision_validation_note = candidate.vision_validation_note or "preview unavailable; requires review after download"
        candidate.rejection_reason = candidate.vision_validation_note
        return True
    if candidate.vision_validation_status not in {"FAILED", "ERROR", "UNCERTAIN", "PREVIEW_UNAVAILABLE"}:
        candidate.vision_validation_note = candidate.vision_validation_note or "preview validation did not pass"
    candidate.match_status = "REJECT"
    candidate.hard_match_pass = "NO"
    candidate.rejection_reason = candidate.vision_validation_note or "preview validation required before download"
    return False


def extract_sampled_frames(video_path: Path, count: int, timeout_sec: int) -> tuple[list[Any], Path | None]:
    try:
        import subprocess
        import tempfile
        from PIL import Image
    except ImportError:
        return [], None
    temp_dir = Path(tempfile.mkdtemp(prefix="broll_frames_"))
    pattern = str(temp_dir / "frame_%03d.jpg")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-i",
                str(video_path),
                "-vf",
                f"fps=1/{max(1, count)}",
                "-frames:v",
                str(count),
                pattern,
            ],
            check=True,
            timeout=timeout_sec,
            capture_output=True,
        )
        frames = [Image.open(path).convert("RGB") for path in sorted(temp_dir.glob("frame_*.jpg"))[:count]]
        return frames, temp_dir
    except Exception:
        return [], temp_dir


def call_clip_frame_model(frames: list[Any], query: str, config: dict[str, Any]) -> float | None:
    try:
        import torch
        import open_clip
    except ImportError:
        return None
    if not frames:
        return None
    model_name = str(config.get("clip_model", "ViT-L-14"))
    pretrained = str(config.get("clip_pretrained", "laion2b_s32b_b82k"))
    model, _, preprocess = open_clip.create_model_and_transforms(model_name, pretrained=pretrained)
    tokenizer = open_clip.get_tokenizer(model_name)
    model.eval()
    with torch.no_grad():
        text_features = model.encode_text(tokenizer([f"a video of {query}"]))
        text_features /= text_features.norm(dim=-1, keepdim=True)
        best = 0.0
        for frame in frames:
            image_features = model.encode_image(preprocess(frame).unsqueeze(0))
            image_features /= image_features.norm(dim=-1, keepdim=True)
            best = max(best, float((image_features @ text_features.T).item()))
    return best


def validate_candidate_clip(candidate: VideoCandidate, plan: ShotPlan, config: dict[str, Any], video_path: Path | None = None) -> VideoCandidate:
    if not bool(config.get("enable_clip_validation", False)):
        candidate.clip_validation_status = "DISABLED"
        candidate.clip_validation_note = "CLIP validation disabled"
        return candidate
    if candidate.hard_match_pass != "YES" or candidate.match_status not in {"EXCELLENT_MATCH", "GOOD_MATCH"}:
        candidate.clip_validation_status = "SKIPPED"
        candidate.clip_validation_note = "CLIP skipped until semantic and hard-match validation pass"
        return candidate
    if bool(config.get("enable_vision_validation", False)) and candidate.vision_validation_status not in {"PASSED", "ACCEPTABLE"}:
        candidate.clip_validation_status = "SKIPPED"
        candidate.clip_validation_note = "CLIP skipped until preview vision validation passes"
        return candidate
    if video_path is None:
        candidate.clip_validation_status = "SKIPPED"
        candidate.clip_validation_note = "CLIP requires sampled frames from a downloaded candidate after preview validation"
        return candidate
    frames, temp_dir = extract_sampled_frames(video_path, int(config.get("perceptual_hash_sample_frames", 5)), int(config.get("clip_validation_timeout_sec", 20)))
    try:
        score = call_clip_frame_model(frames, candidate.query_used or f"{plan.subject} {plan.action}", config)
    finally:
        if temp_dir:
            for path in temp_dir.glob("*"):
                try:
                    path.unlink()
                except OSError:
                    pass
            try:
                temp_dir.rmdir()
            except OSError:
                pass
    if score is None:
        candidate.clip_validation_status = "SKIPPED"
        candidate.clip_validation_note = "CLIP unavailable or no frames extracted"
        return candidate
    candidate.clip_score = round(score, 4)
    if score < float(config.get("clip_min_score", 0.28)):
        candidate.clip_validation_status = "REJECT"
        candidate.match_status = "REJECT"
        candidate.hard_match_pass = "NO"
        candidate.clip_validation_note = f"CLIP score below threshold: {candidate.clip_score}"
        candidate.rejection_reason = candidate.clip_validation_note
    else:
        candidate.clip_validation_status = "PASS"
        candidate.clip_validation_note = f"CLIP score passed: {candidate.clip_score}"
    return candidate


def perceptual_hash_distance(left: str, right: str) -> int:
    try:
        return bin(int(left, 16) ^ int(right, 16)).count("1")
    except ValueError:
        return 999


def perceptual_hashes_near(candidate_hashes: list[str], existing_hashes: list[str], threshold: int) -> bool:
    return any(perceptual_hash_distance(left, right) <= threshold for left in candidate_hashes for right in existing_hashes)


def sampled_perceptual_hashes(video_path: Path, config: dict[str, Any]) -> list[str]:
    if not bool(config.get("enable_perceptual_hash", False)):
        return []
    try:
        import imagehash
    except ImportError:
        return []
    frames, temp_dir = extract_sampled_frames(video_path, int(config.get("perceptual_hash_sample_frames", 5)), int(config.get("clip_validation_timeout_sec", 20)))
    try:
        return [str(imagehash.phash(frame)) for frame in frames]
    finally:
        if temp_dir:
            for path in temp_dir.glob("*"):
                try:
                    path.unlink()
                except OSError:
                    pass
            try:
                temp_dir.rmdir()
            except OSError:
                pass


def candidate_hash(candidate: VideoCandidate) -> str:
    basis = candidate.source_asset_id or candidate.download_url or candidate.source_page_url or f"{candidate.source}:{candidate.creator}:{candidate.title_text}"
    return hashlib.sha1(basis.encode("utf-8", errors="ignore")).hexdigest()


def score_candidate(candidate: VideoCandidate, plan: ShotPlan, scene: Scene) -> VideoCandidate:
    return validate_candidate_semantics(candidate, plan, scene, DEFAULT_CONFIG)


def partial_score(matches: int, target: int, max_points: int) -> int:
    if target <= 0:
        return 0
    return min(max_points, int(round((matches / target) * max_points)))


def orientation_suits_shot(candidate: VideoCandidate, shot: str) -> bool:
    if shot in {"wide", "tracking", "environmental", "lifestyle"}:
        return candidate.width >= candidate.height
    return candidate.width >= 640 and candidate.height >= 360


def match_status(score: int) -> str:
    if score >= EXCELLENT_MATCH_MIN:
        return "EXCELLENT_MATCH"
    if score >= GOOD_MATCH_MIN:
        return "GOOD_MATCH"
    if score >= WEAK_MATCH_MIN:
        return "WEAK_MATCH"
    return "REJECT"


def video_file_size(item: dict[str, Any]) -> int:
    for key in ["file_size", "size", "filesize"]:
        try:
            return int(item.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return 0


def choose_preferred_video_file(files: list[dict[str, Any]], prefer_1080p: bool = True) -> dict[str, Any] | None:
    usable = [item for item in files if item.get("link") or item.get("url")]
    if not usable:
        return None
    if not prefer_1080p:
        return sorted(usable, key=lambda item: int(item.get("width") or 0) * int(item.get("height") or 0), reverse=True)[0]
    landscape = [item for item in usable if int(item.get("width") or 0) >= int(item.get("height") or 0)]
    pool = landscape or usable
    exact_1080 = [item for item in pool if int(item.get("width") or 0) == 1920 and int(item.get("height") or 0) == 1080]
    if exact_1080:
        return sorted(exact_1080, key=video_file_size)[0]
    at_least_1080 = [item for item in pool if int(item.get("width") or 0) >= 1280 and int(item.get("height") or 0) >= 720]
    if at_least_1080:
        return sorted(at_least_1080, key=lambda item: (abs(int(item.get("width") or 0) - 1920) + abs(int(item.get("height") or 0) - 1080), video_file_size(item)))[0]
    return sorted(pool, key=lambda item: int(item.get("width") or 0) * int(item.get("height") or 0), reverse=True)[0]


def search_pexels(query: str, api_key: str, orientation: str, candidate_limit: int) -> list[VideoCandidate]:
    if not api_key:
        return []
    params = urlencode({"query": query, "orientation": orientation, "per_page": candidate_limit})
    data = http_json(
        f"https://api.pexels.com/videos/search?{params}",
        headers={"Authorization": api_key, "User-Agent": "SeniorHealthAI-VisualDirector/2.0"},
    )
    candidates: list[VideoCandidate] = []
    for video in data.get("videos", []):
        chosen = choose_preferred_video_file(video.get("video_files", []), True)
        if not chosen:
            continue
        width = int(chosen.get("width") or video.get("width") or 0)
        height = int(chosen.get("height") or video.get("height") or 0)
        creator = (video.get("user") or {}).get("name", "")
        candidates.append(
            VideoCandidate(
                source="Pexels",
                source_page_url=video.get("url", ""),
                download_url=chosen.get("link", ""),
                license_note="Pexels License",
                creator=creator,
                duration=str(video.get("duration") or ""),
                width=width,
                height=height,
                file_size=video_file_size(chosen),
                title_text=f"{creator} {video.get('url', '')}",
                query_used=query,
                source_asset_id=str(video.get("id", "")),
                tags="",
                description=video.get("url", ""),
                orientation="landscape" if width >= height else "portrait",
                preview_image=video.get("image", ""),
            )
        )
    return candidates


def search_pixabay(query: str, api_key: str, orientation: str, candidate_limit: int) -> list[VideoCandidate]:
    if not api_key:
        return []
    orientation_value = "vertical" if orientation == "portrait" else "horizontal"
    params = urlencode({"key": api_key, "q": query, "video_type": "film", "orientation": orientation_value, "per_page": candidate_limit, "safesearch": "true"})
    data = http_json(f"https://pixabay.com/api/videos/?{params}", headers={"User-Agent": "SeniorHealthAI-VisualDirector/2.0"})
    candidates: list[VideoCandidate] = []
    for video in data.get("hits", []):
        videos = video.get("videos", {})
        chosen = choose_preferred_video_file([item for item in videos.values() if isinstance(item, dict)], True) or {}
        if not chosen.get("url"):
            continue
        candidates.append(
            VideoCandidate(
                source="Pixabay",
                source_page_url=video.get("pageURL", ""),
                download_url=chosen.get("url", ""),
                license_note="Pixabay Content License",
                creator=video.get("user", ""),
                duration=str(video.get("duration") or ""),
                width=int(chosen.get("width") or 0),
                height=int(chosen.get("height") or 0),
                file_size=video_file_size(chosen),
                title_text=video.get("tags", ""),
                query_used=query,
                source_asset_id=str(video.get("id", "")),
                tags=video.get("tags", ""),
                description=video.get("pageURL", ""),
                orientation="landscape" if int(chosen.get("width") or 0) >= int(chosen.get("height") or 0) else "portrait",
                preview_image=video.get("picture_id", ""),
            )
        )
    return candidates


def search_candidates(
    plan: ShotPlan,
    scene: Scene,
    config: dict[str, Any],
    sources: list[str],
    pexels_key: str,
    pixabay_key: str,
    duplicate_index: dict[str, dict[str, str]] | None = None,
    creator_counts: dict[str, int] | None = None,
) -> list[VideoCandidate]:
    orientation = "portrait" if config.get("prefer_vertical_source") else str(config.get("preferred_orientation", "landscape"))
    all_candidates: list[VideoCandidate] = []
    candidate_limit = int(config.get("candidate_pool_size", 15))
    profile = performance_profile(config)
    vision_used = 0
    vision_dedupe_seen: set[str] = set()
    scene_vision_cap = scene_vision_limit(config)
    early_exit = False
    for query in plan.searches:
        query_level = plan.searches.index(query) + 1 if query in plan.searches else 0
        if time_budget_exceeded(config):
            live_log(config, f"time budget reached before query_level={query_level}")
            config["_time_budget_reached"] = True
            break
        live_log(config, f"query_level={query_level} query='{query}'")
        for source in sources:
            if time_budget_exceeded(config):
                live_log(config, f"time budget reached before provider={source}")
                config["_time_budget_reached"] = True
                break
            try:
                before_count = len(all_candidates)
                new_candidates: list[VideoCandidate] = []
                if source == "pexels":
                    if profile:
                        profile.increment("total_api_requests")
                        profile.increment("pexels_api_requests")
                    new_candidates = timed_call(config, "pexels_api", search_pexels, query, pexels_key, orientation, candidate_limit)
                    all_candidates.extend(new_candidates)
                elif source == "pixabay":
                    if profile:
                        profile.increment("total_api_requests")
                        profile.increment("pixabay_api_requests")
                    new_candidates = timed_call(config, "pixabay_api", search_pixabay, query, pixabay_key, orientation, candidate_limit)
                    all_candidates.extend(new_candidates)
                live_log(config, f"query_level={query_level} provider={source} candidates_returned={len(all_candidates) - before_count}")
            except RuntimeError as exc:
                print(f"{source} search warning for '{query}': {exc}")
            query_candidates = [candidate for candidate in all_candidates if candidate.query_used == query]
            for candidate in new_candidates:
                candidate = timed_call(config, "semantic_validation", validate_candidate_semantics, candidate, plan, scene, config)
                timed_call(config, "hard_match", candidate_hard_flags, candidate, plan, scene)
                if duplicate_index is not None and creator_counts is not None:
                    timed_call(config, "duplicate_check", mark_duplicate, candidate, scene, duplicate_index, creator_counts, config)
                if profile and (candidate.match_status == "REJECT" or candidate.hard_match_pass != "YES" or candidate.duplicate_status == "DUPLICATE"):
                    profile.increment("candidates_rejected_before_vision")
            hard_match_count = sum(1 for candidate in query_candidates if candidate.hard_match_pass == "YES")
            remaining_scene_vision = max(0, scene_vision_cap - vision_used)
            query_cap = min(query_vision_limit(config), remaining_scene_vision)
            vision_candidates = [
                candidate
                for candidate in rank_candidates_for_vision(query_candidates, config, query_cap, vision_dedupe_seen)
                if candidate.vision_validation_status in {"", "NOT_RUN"}
            ]
            if profile:
                profile.increment("candidates_rejected_before_vision", max(0, len(query_candidates) - len(vision_candidates)))
            live_log(
                config,
                f"query_level={query_level} hard_match={hard_match_count} sent_to_vision={len(vision_candidates)} vision_used={vision_used}/{scene_vision_cap}",
            )
            evaluated_valid: list[VideoCandidate] = []
            acceptable_first = False
            query_vision_used = 0
            for candidate in vision_candidates:
                if time_budget_exceeded(config):
                    live_log(config, "time budget reached before vision")
                    config["_time_budget_reached"] = True
                    break
                if profile and bool(config.get("enable_vision_validation", False)):
                    profile.increment("candidates_reaching_vision")
                vision_used += 1
                query_vision_used += 1
                live_log(config, f"vision_request={vision_used}/{scene_vision_cap} source={candidate.source} asset={candidate.source_asset_id}")
                candidate = validate_candidate_vision(candidate, plan, scene, config)
                candidate = validate_candidate_clip(candidate, plan, config)
                if candidate_vision_passed(candidate, config):
                    evaluated_valid.append(candidate)
                    if len(evaluated_valid) == 1 and 70 <= candidate.vision_best_frame_score <= 84:
                        acceptable_first = True
                if (
                    candidate.hard_match_pass == "YES"
                    and candidate.relevance_score >= 85
                    and candidate.vision_best_frame_score >= 85
                    and candidate.vision_decision == "VISION_PASS"
                    and candidate.duplicate_status == "UNIQUE"
                ):
                    live_log(config, "early_exit=excellent_valid_candidate")
                    config["_early_exit_reason"] = "excellent valid candidate"
                    early_exit = True
                    break
                if acceptable_first and query_vision_used >= 2:
                    live_log(config, "early_exit=acceptable_candidate_plus_one")
                    config["_early_exit_reason"] = "acceptable candidate plus one comparison"
                    break
                if vision_used >= scene_vision_cap:
                    live_log(config, "early_exit=vision_request_cap")
                    config["_early_exit_reason"] = "vision request cap reached"
                    break
            if early_exit:
                break
            if evaluated_valid:
                live_log(config, "early_exit=valid_candidate_found_for_query")
                config["_early_exit_reason"] = "valid candidate found"
                early_exit = True
                break
            if vision_used >= scene_vision_cap or time_budget_exceeded(config):
                break
        if early_exit or vision_used >= scene_vision_cap or time_budget_exceeded(config):
            break
    return timed_call(config, "candidate_ranking", sorted, all_candidates, key=lambda item: item.relevance_score, reverse=True)


def normalize_asset_url(url: str) -> str:
    url = (url or "").strip().lower()
    url = re.sub(r"[?&](auto|cs|dpr|fit|h|w|fm|dl|download|ixid|crop)=[^&]+", "", url)
    url = re.sub(r"[?&]+$", "", url)
    return url


def selected_asset_keys(source: str, source_asset_id: str, source_page_url: str, download_url: str) -> set[str]:
    keys = set()
    source = (source or "").strip().lower()
    source_asset_id = (source_asset_id or "").strip()
    if source and source_asset_id:
        keys.add(f"asset:{source}:{source_asset_id}")
    for prefix, url in [("page", source_page_url), ("download", download_url)]:
        normalized = normalize_asset_url(url)
        if normalized:
            keys.add(f"{prefix}:{normalized}")
    return keys


def asset_keys(candidate: VideoCandidate) -> set[str]:
    keys = set()
    keys.update(selected_asset_keys(candidate.source, candidate.source_asset_id, candidate.source_page_url, candidate.download_url))
    if candidate.source_asset_id:
        keys.add(f"{candidate.source.lower()}:{candidate.source_asset_id}")
    for url in [candidate.source_page_url, candidate.download_url]:
        normalized = normalize_asset_url(url)
        if normalized:
            keys.add(normalized)
    if candidate.duplicate_hash:
        keys.add(candidate.duplicate_hash)
    return keys


def perceptual_hash_index_keys(candidate: VideoCandidate) -> set[str]:
    return {f"phash:{value}" for value in candidate.perceptual_hashes if value}


def build_duplicate_index(manifest_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for row in manifest_rows:
        for key in selected_asset_keys(
            row.get("source", ""),
            row.get("source_asset_id", ""),
            row.get("source_page_url", "") or row.get("original_url", ""),
            row.get("download_url", ""),
        ):
            index[key] = row
        for value in [
            row.get("source_asset_id", ""),
            row.get("source_page_url", ""),
            row.get("original_url", ""),
            row.get("download_url", ""),
            row.get("duplicate_hash", ""),
        ]:
            if not value:
                continue
            if value == row.get("source_asset_id", ""):
                source = (row.get("source") or "").lower()
                key = f"{source}:{value}" if source else value
                index[key] = row
            index[normalize_asset_url(value)] = row
    return index


def mark_duplicate(candidate: VideoCandidate, scene: Scene, duplicate_index: dict[str, dict[str, str]], creator_counts: dict[str, int], config: dict[str, Any]) -> VideoCandidate:
    if not bool(config.get("prevent_duplicate_assets", True)):
        candidate.duplicate_status = "UNIQUE"
        return candidate
    for key in asset_keys(candidate):
        if key in duplicate_index:
            duplicate = duplicate_index[key]
            candidate.duplicate_status = "DUPLICATE"
            candidate.duplicate_of_scene = duplicate.get("scene_id", "")
            candidate.duplicate_reason = "same source asset ID, source URL, download URL, or duplicate hash"
            return candidate
    if bool(config.get("enable_perceptual_hash", False)) and candidate.perceptual_hashes:
        existing_hashes = [key.split(":", 1)[1] for key in duplicate_index if key.startswith("phash:")]
        if perceptual_hashes_near(candidate.perceptual_hashes, existing_hashes, int(config.get("perceptual_hash_threshold", 8))):
            candidate.duplicate_status = "POSSIBLE_NEAR_DUPLICATE"
            candidate.duplicate_reason = "multi-frame perceptual hash near-duplicate; prefer a unique validated candidate"
            return candidate
    max_creator = int(config.get("max_same_creator_assets", 3))
    if candidate.creator and creator_counts.get(candidate.creator.lower(), 0) >= max_creator:
        candidate.duplicate_status = "POSSIBLE_NEAR_DUPLICATE"
        candidate.duplicate_reason = "creator usage limit reached; possible repeated sequence"
        return candidate
    candidate.duplicate_status = "UNIQUE"
    return candidate


def register_selected_asset(candidate: VideoCandidate, scene: Scene, duplicate_index: dict[str, dict[str, str]], creator_counts: dict[str, int]) -> None:
    row = {
        "scene_id": scene.scene_id,
        "source": candidate.source,
        "source_asset_id": candidate.source_asset_id,
        "source_page_url": candidate.source_page_url,
        "download_url": candidate.download_url,
        "duplicate_hash": candidate.duplicate_hash,
    }
    for key in asset_keys(candidate):
        duplicate_index[key] = row
    for key in perceptual_hash_index_keys(candidate):
        duplicate_index[key] = row
    if candidate.creator:
        creator_counts[candidate.creator.lower()] = creator_counts.get(candidate.creator.lower(), 0) + 1


def top_rejected_summary(candidates: list[VideoCandidate], limit: int) -> str:
    rejected = [candidate for candidate in candidates if candidate.match_status == "REJECT" or candidate.duplicate_status != "UNIQUE"]
    parts = []
    for candidate in rejected[:limit]:
        reason = candidate.rejection_reason or candidate.duplicate_reason or candidate.validation_note or "not selected"
        parts.append(f"{candidate.source_page_url or candidate.download_url} | {candidate.relevance_score} | {candidate.duplicate_status} | {reason}")
    return " || ".join(parts)


def choose_valid_candidate(candidates: list[VideoCandidate], scene: Scene, duplicate_index: dict[str, dict[str, str]], creator_counts: dict[str, int], config: dict[str, Any]) -> tuple[VideoCandidate | None, str]:
    threshold = int(config.get("min_semantic_score", config.get("min_relevance_score", 75)))
    allow_weak = bool(config.get("allow_weak_matches", False))
    possible_near_duplicate: VideoCandidate | None = None
    for candidate in candidates:
        mark_duplicate(candidate, scene, duplicate_index, creator_counts, config)
        if bool(config.get("enable_vision_validation", False)) and (
            candidate.vision_validation_status not in {"PASSED", "ACCEPTABLE"}
            or candidate.vision_best_frame_score < int(config.get("vision_acceptable_threshold", 70))
        ):
            if candidate_preview_unavailable_review_download(candidate):
                pass
            else:
                if candidate.vision_validation_status == "DISABLED":
                    candidate.match_status = "REJECT"
                    candidate.hard_match_pass = "NO"
                    candidate.rejection_reason = "vision validation enabled but candidate remained DISABLED"
                elif candidate.vision_validation_status == "UNCERTAIN":
                    candidate.rejection_reason = candidate.rejection_reason or "vision score requires manual review"
                continue
        if candidate.hard_match_pass != "YES":
            continue
        if candidate.duplicate_status == "DUPLICATE":
            continue
        if candidate.match_status == "WEAK_MATCH" and not allow_weak:
            continue
        if candidate.relevance_score < threshold:
            continue
        if candidate.match_status not in {"EXCELLENT_MATCH", "GOOD_MATCH"} and not allow_weak:
            continue
        if candidate.duplicate_status == "POSSIBLE_NEAR_DUPLICATE":
            possible_near_duplicate = possible_near_duplicate or candidate
            continue
        candidate.selected_for_scene = scene.scene_id
        register_selected_asset(candidate, scene, duplicate_index, creator_counts)
        return candidate, "selected highest-scoring validated unique asset"
    if possible_near_duplicate:
        possible_near_duplicate.selected_for_scene = scene.scene_id
        register_selected_asset(possible_near_duplicate, scene, duplicate_index, creator_counts)
        return possible_near_duplicate, "selected possible near-duplicate because no unique good asset was available"
    return None, "no candidate passed semantic, hard-match, duplicate, and threshold validation"


def candidate_hard_flags(candidate: VideoCandidate, plan: ShotPlan, scene: Scene) -> tuple[bool, bool]:
    text = candidate_text(candidate)
    profile = match_profile(plan, scene)
    subject_ok = term_match(text, profile["subject_terms"])
    age_ok = not profile["required_age_terms"] or term_match(text, profile["required_age_terms"])
    action_ok = term_match(text, profile["action_terms"])
    return subject_ok and age_ok, action_ok


def candidate_reached_vision(candidate: VideoCandidate) -> bool:
    return candidate.vision_validation_status not in {"", "NOT_RUN", "DISABLED"}


def candidate_vision_passed(candidate: VideoCandidate, config: dict[str, Any]) -> bool:
    return (
        candidate.vision_validation_status in {"PASSED", "ACCEPTABLE"}
        and candidate.vision_best_frame_score >= int(config.get("vision_acceptable_threshold", 70))
    )


def candidate_preview_unavailable_review_download(candidate: VideoCandidate) -> bool:
    return (
        candidate.relevance_score >= 90
        and candidate.hard_match_pass == "YES"
        and candidate.duplicate_status == "UNIQUE"
        and candidate.vision_decision == "PREVIEW_UNAVAILABLE"
        and candidate.vision_validation_status == "PREVIEW_UNAVAILABLE"
    )


def successful_download_status_and_notes(candidate: VideoCandidate) -> tuple[str, str]:
    if candidate_preview_unavailable_review_download(candidate):
        return (
            "REVIEW_AFTER_DOWNLOAD",
            f"{candidate.score_notes}; {candidate.vision_validation_note or 'preview unavailable; review after download'}",
        )
    return "DOWNLOADED", candidate.score_notes


def live_log(config: dict[str, Any], message: str) -> None:
    if bool(config.get("_live_logging", False)):
        elapsed = 0.0
        if config.get("_scene_started_at"):
            elapsed = time.perf_counter() - float(config["_scene_started_at"])
        print(f"[broll] {message} elapsed={elapsed:.2f}s")


def semantic_rank_key(candidate: VideoCandidate) -> tuple[int, int, int, int, int]:
    duplicate_bonus = 0 if candidate.duplicate_status == "DUPLICATE" else 1
    return (
        candidate.relevance_score,
        1 if candidate.hard_match_pass == "YES" else 0,
        candidate.demographic_match_score,
        candidate.setting_match_score,
        duplicate_bonus,
    )


def candidate_preview_dedupe_keys(candidate: VideoCandidate) -> set[str]:
    keys: set[str] = set()
    if candidate.source_asset_id:
        keys.add(f"asset:{candidate.source.lower()}:{candidate.source_asset_id}")
    for preview in candidate_preview_images(candidate, DEFAULT_CONFIG):
        normalized = normalize_asset_url(preview)
        if normalized:
            keys.add(f"preview:{normalized}")
    page = normalize_asset_url(candidate.source_page_url)
    if page:
        keys.add(f"page:{page}")
    return keys


def rank_candidates_for_vision(candidates: list[VideoCandidate], config: dict[str, Any], limit: int, seen: set[str] | None = None) -> list[VideoCandidate]:
    unique: list[VideoCandidate] = []
    seen = seen if seen is not None else set()
    for candidate in sorted(candidates, key=semantic_rank_key, reverse=True):
        if candidate.hard_match_pass != "YES":
            continue
        if candidate.duplicate_status == "DUPLICATE":
            continue
        keys = candidate_preview_dedupe_keys(candidate)
        if keys & seen:
            continue
        seen.update(keys)
        unique.append(candidate)
        if len(unique) >= limit:
            break
    return unique


def candidate_is_selectable(candidate: VideoCandidate, config: dict[str, Any]) -> bool:
    threshold = int(config.get("min_semantic_score", config.get("min_relevance_score", 75)))
    allow_weak = bool(config.get("allow_weak_matches", False))
    if bool(config.get("enable_vision_validation", False)) and not candidate_vision_passed(candidate, config) and not candidate_preview_unavailable_review_download(candidate):
        return False
    if candidate.hard_match_pass != "YES":
        return False
    if candidate.duplicate_status == "DUPLICATE":
        return False
    if candidate.match_status == "WEAK_MATCH" and not allow_weak:
        return False
    if candidate.relevance_score < threshold:
        return False
    if candidate.match_status not in {"EXCELLENT_MATCH", "GOOD_MATCH"} and not allow_weak:
        return False
    return True


def rejection_stage_for(candidate: VideoCandidate, plan: ShotPlan, scene: Scene, config: dict[str, Any]) -> str:
    if candidate.selected_for_scene == scene.scene_id:
        return "SELECTED"
    if candidate.duplicate_status == "DUPLICATE":
        return "DUPLICATE"
    hard_subject, hard_action = candidate_hard_flags(candidate, plan, scene)
    if not hard_subject:
        return "HARD_SUBJECT"
    if not hard_action:
        return "HARD_ACTION"
    if bool(config.get("enable_vision_validation", False)) and candidate_reached_vision(candidate) and not candidate_vision_passed(candidate, config):
        return "VISION"
    threshold = int(config.get("min_semantic_score", config.get("min_relevance_score", 75)))
    if candidate.relevance_score < threshold:
        return "THRESHOLD"
    if candidate.match_status == "REJECT":
        return "SEMANTIC"
    return "THRESHOLD"


def best_rejected_candidate(candidates: list[VideoCandidate], selected: VideoCandidate | None = None) -> VideoCandidate | None:
    rejected = [candidate for candidate in candidates if candidate is not selected and not candidate.selected_for_scene]
    if not rejected:
        return None
    return sorted(
        rejected,
        key=lambda item: (
            item.relevance_score,
            item.vision_best_frame_score,
            item.subject_match_score + item.action_match_score + item.setting_match_score,
        ),
        reverse=True,
    )[0]


def stage_counts_for(candidates: list[VideoCandidate], plan: ShotPlan, scene: Scene, config: dict[str, Any]) -> dict[str, int]:
    threshold = int(config.get("min_semantic_score", config.get("min_relevance_score", 75)))
    return {
        "provider_returned_count": len(candidates),
        "basic_filter_pass_count": len(candidates),
        "semantic_pass_count": sum(1 for candidate in candidates if candidate.relevance_score >= threshold),
        "hard_match_pass_count": sum(1 for candidate in candidates if candidate.hard_match_pass == "YES"),
        "vision_pass_count": sum(1 for candidate in candidates if candidate_vision_passed(candidate, config)),
        "duplicate_pass_count": sum(1 for candidate in candidates if candidate.duplicate_status != "DUPLICATE"),
        "selectable_count": sum(1 for candidate in candidates if candidate_is_selectable(candidate, config)),
    }


def candidate_diagnostic_rows(scene: Scene, plan: ShotPlan, candidates: list[VideoCandidate], selected: VideoCandidate | None, config: dict[str, Any]) -> list[dict[str, str]]:
    counts = stage_counts_for(candidates, plan, scene, config)
    if not candidates:
        return [
            {
                "scene_id": scene.scene_id,
                "query_level": "",
                "search_query": plan.searches[0] if plan.searches else "",
                "provider": "",
                "candidate_asset_id": "",
                "candidate_title": "",
                "candidate_url": "",
                "basic_filter_pass": "NO",
                "semantic_score": "0",
                "semantic_status": "NO_CANDIDATES",
                "subject_match_score": "0",
                "action_match_score": "0",
                "setting_match_score": "0",
                "demographic_match_score": "0",
                "hard_subject_pass": "NO",
                "hard_action_pass": "NO",
                "hard_match_pass": "NO",
                "vision_status": "",
                "vision_best_frame_score": "0",
                "vision_average_frame_score": "0",
                "vision_decision": "",
                "vision_raw_response_excerpt": "",
                "vision_parse_status": "",
                "vision_parse_error": "",
                "vision_repair_attempted": "",
                "vision_repair_success": "",
                "duplicate_status": "",
                "final_candidate_status": "NO_CANDIDATES",
                "rejection_stage": "BASIC_FILTER",
                "rejection_reason": "No candidates were returned after provider/basic filtering.",
                **{key: str(value) for key, value in counts.items()},
            }
        ]
    rows: list[dict[str, str]] = []
    for candidate in candidates:
        hard_subject, hard_action = candidate_hard_flags(candidate, plan, scene)
        stage = rejection_stage_for(candidate, plan, scene, config)
        rows.append(
            {
                "scene_id": scene.scene_id,
                "query_level": str((plan.searches.index(candidate.query_used) + 1) if candidate.query_used in plan.searches else ""),
                "search_query": candidate.query_used,
                "provider": candidate.source,
                "candidate_asset_id": candidate.source_asset_id,
                "candidate_title": candidate.title_text,
                "candidate_url": candidate.source_page_url or candidate.download_url,
                "basic_filter_pass": "YES",
                "semantic_score": str(candidate.relevance_score),
                "semantic_status": candidate.match_status,
                "subject_match_score": str(candidate.subject_match_score),
                "action_match_score": str(candidate.action_match_score),
                "setting_match_score": str(candidate.setting_match_score),
                "demographic_match_score": str(candidate.demographic_match_score),
                "hard_subject_pass": "YES" if hard_subject else "NO",
                "hard_action_pass": "YES" if hard_action else "NO",
                "hard_match_pass": candidate.hard_match_pass,
                "vision_status": candidate.vision_validation_status,
                "vision_best_frame_score": str(candidate.vision_best_frame_score),
                "vision_average_frame_score": str(candidate.vision_average_frame_score),
                "vision_decision": candidate.vision_decision,
                "vision_raw_response_excerpt": candidate.vision_raw_response_excerpt,
                "vision_parse_status": candidate.vision_parse_status,
                "vision_parse_error": candidate.vision_parse_error,
                "vision_repair_attempted": candidate.vision_repair_attempted,
                "vision_repair_success": candidate.vision_repair_success,
                "duplicate_status": candidate.duplicate_status,
                "final_candidate_status": "SELECTED" if candidate is selected or candidate.selected_for_scene == scene.scene_id else "REJECTED",
                "rejection_stage": stage,
                "rejection_reason": candidate.rejection_reason or candidate.duplicate_reason or candidate.validation_note,
                **{key: str(value) for key, value in counts.items()},
            }
        )
    return rows


def write_candidate_diagnostics(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = dedupe_columns(CANDIDATE_DIAGNOSTIC_COLUMNS)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def print_performance_profile(scene_id: str, profile: PerformanceProfile) -> None:
    timings = profile.timings
    counts = profile.counts
    vision_requests = counts.get("vision_requests", 0)
    preview_downloads = counts.get("preview_downloads", 0)
    print(f"Performance profile for scene {scene_id}:")
    for stage in [
        "query_generation",
        "pexels_api",
        "pixabay_api",
        "semantic_validation",
        "hard_match",
        "preview_download",
        "vision_validation",
        "duplicate_check",
        "candidate_ranking",
        "final_selection",
    ]:
        print(f"- {stage}: {timings.get(stage, 0.0):.3f}s")
    print(f"- total_api_requests: {counts.get('total_api_requests', 0)}")
    print(f"- total_vision_requests: {vision_requests}")
    print(f"- average_vision_request_time: {(timings.get('vision_validation', 0.0) / vision_requests if vision_requests else 0.0):.3f}s")
    print(f"- average_preview_download_time: {(timings.get('preview_download', 0.0) / preview_downloads if preview_downloads else 0.0):.3f}s")
    print(f"- candidates_reaching_vision: {counts.get('candidates_reaching_vision', 0)}")
    print(f"- candidates_rejected_before_vision: {counts.get('candidates_rejected_before_vision', 0)}")
    bottlenecks = sorted(timings.items(), key=lambda item: item[1], reverse=True)[:3]
    print("- top_3_bottlenecks: " + "; ".join(f"{stage}={elapsed:.3f}s" for stage, elapsed in bottlenecks))


def best_manual_review_candidate(candidates: list[VideoCandidate], config: dict[str, Any]) -> VideoCandidate | None:
    lower = int(config.get("vision_uncertain_threshold", 50))
    upper = int(config.get("vision_acceptable_threshold", 70))
    high_confidence_previewless = [
        candidate
        for candidate in candidates
        if candidate.relevance_score >= 90
        and candidate.vision_validation_status == "PREVIEW_UNAVAILABLE"
        and candidate.duplicate_status != "DUPLICATE"
    ]
    if high_confidence_previewless:
        return sorted(high_confidence_previewless, key=lambda item: item.relevance_score, reverse=True)[0]
    reviewable = [
        candidate
        for candidate in candidates
        if lower <= candidate.vision_best_frame_score < upper
        and candidate.vision_validation_status == "UNCERTAIN"
        and candidate.duplicate_status != "DUPLICATE"
    ]
    if not reviewable:
        return None
    return sorted(reviewable, key=lambda item: (item.vision_best_frame_score, item.relevance_score), reverse=True)[0]


def is_repetition_blocked(plan: ShotPlan, scene: Scene, used: dict[str, list[str]], config: dict[str, Any]) -> bool:
    window = int(config.get("repetition_window", 8))
    max_action = int(config.get("max_same_action_in_window", 2))
    recent_actions = used.setdefault("actions", [])[-window:]
    recent_shots = used.setdefault("shots", [])
    same_action_count = sum(1 for action in recent_actions if action == plan.action)
    if same_action_count >= max_action:
        return True
    recent_base = used.setdefault("base_queries", [])[-window:]
    if recent_base.count(base_query_key(plan.searches[0])) >= 2:
        return True
    max_same_shot = int(config.get("max_same_shot_consecutive", 3))
    if len(recent_shots) >= max_same_shot and all(shot == plan.recommended_shot for shot in recent_shots[-max_same_shot:]):
        return True
    return False


def update_repetition_state(plan: ShotPlan, used: dict[str, list[str]]) -> None:
    used.setdefault("actions", []).append(plan.action)
    used.setdefault("shots", []).append(plan.recommended_shot)
    used.setdefault("queries", []).append(plan.searches[0])
    used.setdefault("normalized_queries", []).append(normalize_query(plan.searches[0]))
    used.setdefault("base_queries", []).append(base_query_key(plan.searches[0]))
    used.setdefault("categories", []).append(query_category(plan.searches[0]))
    for key in ["actions", "shots", "queries", "normalized_queries", "base_queries", "categories"]:
        used[key] = used[key][-50:]


def read_existing_manifest(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = dedupe_columns(MANIFEST_COLUMNS)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def is_selected_stock_row(row: dict[str, str]) -> bool:
    source = (row.get("source") or "").strip()
    status = (row.get("status") or "").strip()
    fallback_sources = {"AI_IMAGE_RECOMMENDED", "GRAPHIC_RECOMMENDED", "AVATAR_RECOMMENDED", "MANUAL_SEARCH_REQUIRED", "NOT_SEARCHED"}
    return bool(source) and source not in fallback_sources and status in {"MATCHED_DRY_RUN", "DOWNLOADED", "REVIEW_AFTER_DOWNLOAD"}


def validate_manifest_integrity(rows: list[dict[str, str]], config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, str] = {}
    duplicate_keys: set[str] = set()
    for row in rows:
        if not is_selected_stock_row(row):
            continue
        scene_id = row.get("scene_id", "")
        keys = selected_asset_keys(
            row.get("source", ""),
            row.get("source_asset_id", ""),
            row.get("original_url", "") or row.get("source_page_url", ""),
            row.get("download_url", ""),
        )
        for key in keys:
            if key in seen and seen[key] != scene_id:
                duplicate_keys.add(key)
                errors.append(f"selected duplicate asset key {key} appears in scenes {seen[key]} and {scene_id}")
            else:
                seen[key] = scene_id
        if bool(config.get("enable_vision_validation", False)) and row.get("vision_validation_status") == "DISABLED":
            errors.append(f"scene {scene_id} selected stock asset with DISABLED vision validation")
    for row in rows:
        if not is_selected_stock_row(row):
            continue
        keys = selected_asset_keys(
            row.get("source", ""),
            row.get("source_asset_id", ""),
            row.get("original_url", "") or row.get("source_page_url", ""),
            row.get("download_url", ""),
        )
        if keys & duplicate_keys and row.get("duplicate_status") == "UNIQUE":
            errors.append(f"scene {row.get('scene_id', '')} duplicate_status UNIQUE conflicts with repeated asset key")
    return errors


def scene_has_valid_manifest_asset(rows: list[dict[str, str]], scene_id: str) -> bool:
    for row in rows:
        if row.get("scene_id") != scene_id:
            continue
        if not is_selected_stock_row(row):
            continue
        if row.get("source_asset_id") or row.get("original_url") or row.get("download_url"):
            return True
    return False


def dedupe_columns(columns: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for column in columns:
        if column not in seen:
            seen.add(column)
            result.append(column)
    return result


def upsert_manifest_row(rows: list[dict[str, str]], new_row: dict[str, str]) -> list[dict[str, str]]:
    filtered = [row for row in rows if row.get("asset_id") != new_row["asset_id"]]
    filtered.append(new_row)
    return filtered


def write_visual_director_report(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=VISUAL_DIRECTOR_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in VISUAL_DIRECTOR_COLUMNS})


def write_collection_report(path: Path, stats: CollectionStats, settings: dict[str, Any], dry_run: bool, sources: list[str]) -> None:
    lines = [
        "# B-roll Collection Report",
        "",
        "## Run Summary",
        "",
        f"- Mode: {'dry-run/report-first' if dry_run else 'download'}",
        f"- Sources enabled: {', '.join(sources) if sources else 'none'}",
        f"- Total scenes analyzed: {stats.total_scenes}",
        f"- Scenes searched as B-roll: {stats.searched_scenes}",
        f"- Dry-run approved matches: {stats.dry_run_matches}",
        f"- Downloaded clips: {stats.downloaded}",
        f"- Rejected or weak matches: {stats.rejected}",
        f"- Fallback recommendations: {stats.fallbacks}",
        f"- Manual review required: {stats.manual_review}",
        f"- Duplicate assets blocked: {stats.duplicates_blocked}",
        "",
        "## Settings",
        "",
        f"- min_relevance_score: {settings['min_relevance_score']}",
        f"- min_semantic_score: {settings.get('min_semantic_score', 75)}",
        f"- require_subject_match: {settings.get('require_subject_match', True)}",
        f"- require_action_match: {settings.get('require_action_match', True)}",
        f"- prevent_duplicate_assets: {settings.get('prevent_duplicate_assets', True)}",
        f"- candidate_pool_size: {settings.get('candidate_pool_size', 15)}",
        f"- enable_vision_validation: {settings.get('enable_vision_validation', False)}",
        f"- vision_validation_model: {settings.get('vision_validation_model', '')}",
        f"- vision_validation_required: {settings.get('vision_validation_required', False)}",
        f"- allow_weak_matches: {settings['allow_weak_matches']}",
        f"- max_downloads_per_scene: {settings['max_downloads_per_scene']}",
        f"- repetition_window: {settings['repetition_window']}",
        f"- preferred_orientation: {settings['preferred_orientation']}",
        "",
        "## Safety Notes",
        "",
        "- Weak matches are not downloaded unless explicitly enabled.",
        "- Sensitive medical scenes prefer avatar, graphic, document-style, or manual-review fallback.",
        "- Duplicate clip URLs and repeated nearby actions are blocked or routed to review.",
        "- Narration is never modified by this collector.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def manifest_row_for(
    scene: Scene,
    plan: ShotPlan,
    candidate: VideoCandidate | None,
    asset_id: str,
    local_path: str,
    status: str,
    notes: str,
    best_rejected: VideoCandidate | None = None,
    best_rejected_stage: str = "",
) -> dict[str, str]:
    source = candidate.source if candidate else plan.fallback_recommendation
    query = candidate.query_used if candidate else plan.searches[0]
    metrics_candidate = candidate or best_rejected
    best_stage = best_rejected_stage
    return {
        "asset_id": asset_id,
        "scene_id": scene.scene_id,
        "source": source,
        "search_query": query,
        "local_path": local_path,
        "original_url": candidate.source_page_url if candidate else "",
        "license": candidate.license_note if candidate else "",
        "creator": candidate.creator if candidate else "",
        "duration": candidate.duration if candidate else scene.duration,
        "resolution": candidate.resolution if candidate else "",
        "status": status,
        "notes": notes,
        "scene_intent": plan.scene_intent,
        "recommended_visual_mode": plan.recommended_visual_mode,
        "search_query_used": query,
        "relevance_score": str(metrics_candidate.relevance_score if metrics_candidate else 0),
        "match_status": candidate.match_status if candidate else status,
        "source_page_url": candidate.source_page_url if candidate else "",
        "download_url": candidate.download_url if candidate else "",
        "license_note": candidate.license_note if candidate else "",
        "width": str(candidate.width if candidate else ""),
        "height": str(candidate.height if candidate else ""),
        "duplicate_hash": candidate.duplicate_hash if candidate else "",
        "manual_review_required": plan.manual_review_required,
        "source_asset_id": candidate.source_asset_id if candidate else "",
        "semantic_score": str(metrics_candidate.relevance_score if metrics_candidate else 0),
        "hard_match_pass": metrics_candidate.hard_match_pass if metrics_candidate else "NO",
        "vision_validation_status": metrics_candidate.vision_validation_status if metrics_candidate else "",
        "vision_validation_note": metrics_candidate.vision_validation_note if metrics_candidate else "",
        "vision_subject_score": str(metrics_candidate.vision_subject_score if metrics_candidate else 0),
        "vision_action_score": str(metrics_candidate.vision_action_score if metrics_candidate else 0),
        "vision_setting_score": str(metrics_candidate.vision_setting_score if metrics_candidate else 0),
        "vision_support_score": str(metrics_candidate.vision_support_score if metrics_candidate else 0),
        "vision_safety_score": str(metrics_candidate.vision_safety_score if metrics_candidate else 0),
        "vision_best_frame_score": str(metrics_candidate.vision_best_frame_score if metrics_candidate else 0),
        "vision_average_frame_score": str(metrics_candidate.vision_average_frame_score if metrics_candidate else 0),
        "vision_decision": metrics_candidate.vision_decision if metrics_candidate else "",
        "vision_rejection_reason": metrics_candidate.vision_rejection_reason if metrics_candidate else "",
        "vision_raw_response_excerpt": metrics_candidate.vision_raw_response_excerpt if metrics_candidate else "",
        "vision_parse_status": metrics_candidate.vision_parse_status if metrics_candidate else "",
        "vision_parse_error": metrics_candidate.vision_parse_error if metrics_candidate else "",
        "vision_repair_attempted": metrics_candidate.vision_repair_attempted if metrics_candidate else "",
        "vision_repair_success": metrics_candidate.vision_repair_success if metrics_candidate else "",
        "duplicate_status": candidate.duplicate_status if candidate else "",
        "selected_for_scene": candidate.selected_for_scene if candidate else "",
        "validation_note": metrics_candidate.validation_note if metrics_candidate else notes,
        "best_rejected_asset_id": best_rejected.source_asset_id if best_rejected else "",
        "best_rejected_url": (best_rejected.source_page_url or best_rejected.download_url) if best_rejected else "",
        "best_rejected_semantic_score": str(best_rejected.relevance_score if best_rejected else 0),
        "best_rejected_vision_score": str(best_rejected.vision_best_frame_score if best_rejected else 0),
        "best_rejected_stage": best_stage,
        "best_rejected_reason": (best_rejected.rejection_reason or best_rejected.duplicate_reason or best_rejected.validation_note) if best_rejected else "",
    }


def report_row_for(
    scene: Scene,
    plan: ShotPlan,
    candidate: VideoCandidate | None,
    local_file: str,
    match_status_value: str,
    rejection_reason: str,
    candidate_count: int = 0,
    selection_reason: str = "",
    top_rejected: str = "",
) -> dict[str, str]:
    searches = plan.searches + ["", "", "", ""]
    return {
        "scene_id": scene.scene_id,
        "narration_excerpt": compact_text(scene.narration),
        "original_visual_mode": scene.original_visual_mode,
        "recommended_visual_mode": plan.recommended_visual_mode,
        "scene_intent": plan.scene_intent,
        "viewer_emotion": plan.viewer_emotion,
        "story_function": plan.story_function,
        "medical_context": plan.medical_context,
        "recommended_shot": plan.recommended_shot,
        "subject": plan.subject,
        "action": plan.action,
        "setting": plan.setting,
        "mood": plan.mood,
        "primary_search": searches[0],
        "alternative_search_1": searches[1],
        "alternative_search_2": searches[2],
        "alternative_search_3": searches[3],
        "selected_source": candidate.source if candidate else "",
        "selected_asset_url": candidate.source_page_url if candidate else "",
        "local_file": local_file,
        "candidate_count": str(candidate_count),
        "selected_asset_id": candidate.source_asset_id if candidate else "",
        "selected_asset_title": candidate.title_text if candidate else "",
        "selected_asset_tags": candidate.tags if candidate else "",
        "subject_match_score": str(candidate.subject_match_score if candidate else 0),
        "action_match_score": str(candidate.action_match_score if candidate else 0),
        "setting_match_score": str(candidate.setting_match_score if candidate else 0),
        "demographic_match_score": str(candidate.demographic_match_score if candidate else 0),
        "shot_match_score": str(candidate.shot_match_score if candidate else 0),
        "narration_relevance_score": str(candidate.narration_relevance_score if candidate else 0),
        "medical_safety_score": str(candidate.medical_safety_score if candidate else 0),
        "total_relevance_score": str(candidate.relevance_score if candidate else 0),
        "relevance_score": str(candidate.relevance_score if candidate else 0),
        "match_status": match_status_value,
        "hard_match_pass": candidate.hard_match_pass if candidate else "NO",
        "vision_validation_status": candidate.vision_validation_status if candidate else "",
        "vision_validation_note": candidate.vision_validation_note if candidate else "",
        "vision_subject_score": str(candidate.vision_subject_score if candidate else 0),
        "vision_action_score": str(candidate.vision_action_score if candidate else 0),
        "vision_setting_score": str(candidate.vision_setting_score if candidate else 0),
        "vision_support_score": str(candidate.vision_support_score if candidate else 0),
        "vision_safety_score": str(candidate.vision_safety_score if candidate else 0),
        "vision_best_frame_score": str(candidate.vision_best_frame_score if candidate else 0),
        "vision_average_frame_score": str(candidate.vision_average_frame_score if candidate else 0),
        "vision_decision": candidate.vision_decision if candidate else "",
        "vision_rejection_reason": candidate.vision_rejection_reason if candidate else "",
        "vision_raw_response_excerpt": candidate.vision_raw_response_excerpt if candidate else "",
        "vision_parse_status": candidate.vision_parse_status if candidate else "",
        "vision_parse_error": candidate.vision_parse_error if candidate else "",
        "vision_repair_attempted": candidate.vision_repair_attempted if candidate else "",
        "vision_repair_success": candidate.vision_repair_success if candidate else "",
        "duplicate_status": candidate.duplicate_status if candidate else "",
        "duplicate_of_scene": candidate.duplicate_of_scene if candidate else "",
        "duplicate_reason": candidate.duplicate_reason if candidate else "",
        "selection_reason": selection_reason or top_rejected,
        "sequence_id": plan.sequence_id,
        "sequence_position": plan.sequence_position,
        "continuity_note": plan.continuity_note,
        "fallback_recommendation": plan.fallback_recommendation,
        "rejection_reason": rejection_reason,
        "manual_review_required": plan.manual_review_required,
    }


def source_list(source_args: list[str] | None) -> list[str]:
    if source_args:
        return [item.lower() for item in source_args]
    return ["pexels", "pixabay"]


def collect_broll(
    project: Path,
    dry_run: bool | None = None,
    scene_id: str | None = None,
    min_score: int | None = None,
    sources: list[str] | None = None,
    report_only: bool = False,
    force: bool = False,
    show_candidates: bool = False,
    candidate_limit: int | None = None,
    validate_only: bool = False,
    fast_download: bool = False,
    trace_scene: bool = False,
    profile_scene: bool = False,
    profile_fast: bool = False,
) -> CollectionStats:
    project = project.resolve()
    if not project.exists() or not project.is_dir():
        raise FileNotFoundError(f"Project folder not found: {project}")
    require_input_files(project)

    config = load_config()
    if trace_scene or profile_scene or profile_fast:
        dry_run = True
        show_candidates = True
    if profile_scene or profile_fast:
        config["_performance_profile"] = PerformanceProfile()
        config["_live_logging"] = True
    if profile_fast:
        config["_profile_fast"] = True
        config["candidate_pool_size"] = int(config.get("profile_fast_candidate_pool_size", 3))
    if dry_run is None:
        dry_run = bool(config.get("dry_run", True))
    if min_score is not None:
        config["min_relevance_score"] = min_score
        config["min_semantic_score"] = min_score
    if candidate_limit is not None:
        config["candidate_pool_size"] = candidate_limit
    if fast_download:
        config["_fast_download"] = True
        apply_fast_download_config(config)
    if validate_only:
        report_only = True
        dry_run = True
    enabled_sources = source_list(sources)

    pexels_key = get_api_key("PEXELS_API_KEY")
    pixabay_key = get_api_key("PIXABAY_API_KEY")
    if not pexels_key and not pixabay_key:
        print("No API keys found. Visual Director reports will be created without live stock searches.")
    print(
        "Validation toggles: "
        f"vision={'ON' if config.get('enable_vision_validation') else 'OFF'}, "
        f"CLIP={'ON' if config.get('enable_clip_validation') else 'OFF'}, "
        f"pHash={'ON' if config.get('enable_perceptual_hash') else 'OFF'}"
    )

    scenes = parse_production(project)
    if scene_id:
        scenes = [scene for scene in scenes if scene.scene_id == scene_id]
        if not scenes:
            raise ValueError(f"Scene not found: {scene_id}")

    manifest_path = project / MANIFEST_FILE
    candidate_diagnostics_path = project / CANDIDATE_DIAGNOSTICS_FILE
    vision_cache_path = project / VISION_CACHE_FILE
    director_report_path = project / VISUAL_DIRECTOR_REPORT_FILE
    collection_report_path = project / COLLECTION_REPORT_FILE
    manifest_rows = read_existing_manifest(manifest_path)
    config["_vision_cache_path"] = str(vision_cache_path)
    config["_vision_cache"] = load_vision_cache(vision_cache_path) if bool(config.get("enable_vision_cache", True)) else {}
    config["_force_vision_cache_refresh"] = bool(force)
    output_dir = project / BROLL_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    duplicate_index = build_duplicate_index(manifest_rows)
    creator_counts: dict[str, int] = {}
    for row in manifest_rows:
        creator = (row.get("creator") or "").lower()
        if creator:
            creator_counts[creator] = creator_counts.get(creator, 0) + 1
    used: dict[str, list[str]] = {
        "actions": [],
        "shots": [],
        "queries": [],
        "normalized_queries": [],
        "base_queries": [],
        "categories": [],
    }
    previous_shots: list[str] = []
    sequence_map = build_story_sequences(scenes, config)
    report_rows: list[dict[str, str]] = []
    candidate_diagnostic_rows_out: list[dict[str, str]] = []
    stats = CollectionStats(total_scenes=len(scenes))

    for index, scene in enumerate(scenes, start=1):
        scene_started = time.perf_counter()
        config["_scene_started_at"] = scene_started
        config["_time_budget_reached"] = False
        config["_early_exit_reason"] = ""
        search_elapsed = 0.0
        validation_elapsed = 0.0
        download_elapsed = 0.0
        plan_started = time.perf_counter()
        plan = plan_scene(scene, len(scenes), config, previous_shots, sequence_map[scene.scene_id])
        plan.searches = select_diverse_primary(plan.searches, used, config)
        profile = performance_profile(config)
        if profile:
            profile.add_time("query_generation", time.perf_counter() - plan_started)
        asset_id = f"broll_{scene.scene_id or index:0>3}"
        local_file = ""
        selected: VideoCandidate | None = None
        match_value = "NOT_SEARCHED"
        rejection_reason = plan.rejection_reason
        candidates: list[VideoCandidate] = []
        selection_reason = ""
        skipped_existing_asset = False

        should_search = plan.recommended_visual_mode == "broll" and not report_only
        if should_search and not force and scene_has_valid_manifest_asset(manifest_rows, scene.scene_id):
            should_search = False
            skipped_existing_asset = True
            match_value = "SKIPPED_EXISTING_ASSET"
            rejection_reason = "Existing valid manifest asset found; use --force to replace."
        if should_search and is_repetition_blocked(plan, scene, used, config):
            should_search = False
            plan.manual_review_required = "YES"
            plan.fallback_recommendation = "MANUAL_SEARCH_REQUIRED"
            rejection_reason = "Repetition control blocked another nearby similar B-roll search."
            stats.fallbacks += 1

        if should_search:
            stats.searched_scenes += 1
            search_started = time.perf_counter()
            candidates = search_candidates(plan, scene, config, enabled_sources, pexels_key, pixabay_key, duplicate_index, creator_counts)
            search_elapsed = time.perf_counter() - search_started
            validation_started = time.perf_counter()
            for candidate in candidates:
                timed_call(config, "duplicate_check", mark_duplicate, candidate, scene, duplicate_index, creator_counts, config)
            if not force:
                selected, selection_reason = timed_call(config, "final_selection", choose_valid_candidate, candidates, scene, duplicate_index, creator_counts, config)
            else:
                selected, selection_reason = timed_call(config, "final_selection", choose_valid_candidate, candidates, scene, {}, {}, {**config, "prevent_duplicate_assets": False})
            validation_elapsed = time.perf_counter() - validation_started
            stats.duplicates_blocked += len([candidate for candidate in candidates if candidate.duplicate_status == "DUPLICATE"])
            if selected:
                match_value = selected.match_status
                stats.source_counts[selected.source] = stats.source_counts.get(selected.source, 0) + 1
                local_path = output_dir / f"{asset_id}_{selected.source.lower()}.mp4"
                local_file = str(local_path.relative_to(project))
                if dry_run:
                    status = "MATCHED_DRY_RUN"
                    stats.dry_run_matches += 1
                    notes = selected.score_notes
                else:
                    status = "DOWNLOAD_FAILED"
                    notes = selected.score_notes
                    attempted_video_download = False
                    preview_rejection_notes: list[str] = []
                    download_candidates = [selected] + [
                        candidate for candidate in candidates
                        if candidate is not selected
                        and candidate.hard_match_pass == "YES"
                        and candidate.duplicate_status == "UNIQUE"
                        and candidate.relevance_score >= int(config.get("min_semantic_score", 75))
                        and candidate.match_status in {"EXCELLENT_MATCH", "GOOD_MATCH"}
                    ]
                    for download_candidate in download_candidates:
                        download_started = time.perf_counter()
                        selected = download_candidate
                        local_path = output_dir / f"{asset_id}_{selected.source.lower()}.mp4"
                        local_file = str(local_path.relative_to(project))
                        if not candidate_preview_passes_before_download(selected, plan, scene, config):
                            preview_rejection_notes.append(f"{selected.source_asset_id or selected.source_page_url}: {selected.vision_validation_note or selected.rejection_reason}")
                            local_file = ""
                            continue
                        attempted_video_download = True
                        try:
                            print(
                                f"Downloading {scene.scene_id}: {selected.source} {selected.source_asset_id} "
                                f"{selected.resolution or 'unknown resolution'} "
                                f"{selected.file_size or 'unknown'} bytes expected"
                            )
                            download_file(
                                selected.download_url,
                                local_path,
                                retries=int(config.get("download_retries", 2)),
                                connect_timeout=int(config.get("download_connect_timeout_sec", 10)),
                                download_timeout=int(config.get("download_timeout_sec", 90)),
                            )
                            download_elapsed += time.perf_counter() - download_started
                            selected.duplicate_hash = file_hash(local_path)
                            if bool(config.get("enable_clip_validation", False)):
                                validate_candidate_clip(selected, plan, config, local_path)
                                if selected.clip_validation_status == "REJECT":
                                    status = "DOWNLOAD_FAILED"
                                    notes = selected.rejection_reason
                                    local_file = ""
                                    continue
                            if bool(config.get("enable_perceptual_hash", False)):
                                selected.perceptual_hashes = sampled_perceptual_hashes(local_path, config)
                                existing_hashes = [key.split(":", 1)[1] for key in duplicate_index if key.startswith("phash:")]
                                if selected.perceptual_hashes and perceptual_hashes_near(selected.perceptual_hashes, existing_hashes, int(config.get("perceptual_hash_threshold", 8))):
                                    selected.duplicate_status = "POSSIBLE_NEAR_DUPLICATE"
                                    selected.duplicate_reason = "multi-frame perceptual hash near-duplicate; trying next unique candidate"
                                    local_file = ""
                                    continue
                            register_selected_asset(selected, scene, duplicate_index, creator_counts)
                            stats.downloaded += 1
                            status, notes = successful_download_status_and_notes(selected)
                            break
                        except RuntimeError as exc:
                            status = "DOWNLOAD_FAILED"
                            notes = f"{selected.score_notes}; {exc}"
                            local_file = ""
                            download_elapsed += time.perf_counter() - download_started
                    if not attempted_video_download and preview_rejection_notes:
                        stats.rejected += 1
                        stats.fallbacks += 1
                        match_value = plan.fallback_recommendation or "MANUAL_SEARCH_REQUIRED"
                        status = match_value
                        rejection_reason = "No candidate passed preview validation before video download. " + " | ".join(preview_rejection_notes[:3])
                        notes = rejection_reason
                        selected = None
                        local_file = ""
                manifest_rows = upsert_manifest_row(
                    manifest_rows,
                    manifest_row_for(scene, plan, selected, asset_id, local_file, status, notes),
                )
            else:
                stats.rejected += 1
                stats.fallbacks += 1
                rejected = best_rejected_candidate(candidates, selected)
                rejected_stage = rejection_stage_for(rejected, plan, scene, config) if rejected else ""
                manual_review_candidate = best_manual_review_candidate(candidates, config) if bool(config.get("enable_vision_validation", False)) else None
                manifest_candidate = None
                if manual_review_candidate:
                    plan.manual_review_required = "YES"
                    plan.fallback_recommendation = "MANUAL_REVIEW_REQUIRED"
                    match_value = "MANUAL_REVIEW_REQUIRED"
                    manifest_candidate = manual_review_candidate
                    rejected = rejected or manual_review_candidate
                    rejected_stage = rejection_stage_for(rejected, plan, scene, config)
                    rejection_reason = (
                        "Best candidate requires manual review; "
                        f"vision score {manual_review_candidate.vision_best_frame_score} is below auto-download threshold. "
                        f"Preview: {manual_review_candidate.preview_image or manual_review_candidate.source_page_url}. "
                        f"Reason: {manual_review_candidate.vision_rejection_reason or manual_review_candidate.vision_validation_note}"
                    )
                else:
                    match_value = plan.fallback_recommendation if plan.fallback_recommendation else "MANUAL_SEARCH_REQUIRED"
                    rejection_reason = selection_reason or "No result met semantic threshold; weak or invalid matches were not downloaded."
                manifest_rows = upsert_manifest_row(
                    manifest_rows,
                    manifest_row_for(scene, plan, manifest_candidate, asset_id, "", match_value, rejection_reason, rejected, rejected_stage),
                )
        else:
            if not skipped_existing_asset:
                stats.fallbacks += 1
                if plan.manual_review_required == "YES":
                    stats.manual_review += 1
                match_value = plan.fallback_recommendation
                manifest_rows = upsert_manifest_row(
                    manifest_rows,
                    manifest_row_for(scene, plan, None, asset_id, "", match_value, rejection_reason or "B-roll not recommended for this scene."),
                )

        if plan.manual_review_required == "YES":
            stats.manual_review += 1
        top_rejected = top_rejected_summary(candidates, int(config.get("show_top_rejected_candidates", 3))) if (show_candidates or dry_run) else ""
        candidate_diagnostic_rows_out.extend(candidate_diagnostic_rows(scene, plan, candidates, selected, config))
        if trace_scene:
            counts = stage_counts_for(candidates, plan, scene, config)
            print(f"Trace scene {scene.scene_id} stage counts:")
            for key in [
                "provider_returned_count",
                "basic_filter_pass_count",
                "semantic_pass_count",
                "hard_match_pass_count",
                "vision_pass_count",
                "duplicate_pass_count",
                "selectable_count",
            ]:
                print(f"- {key}: {counts[key]}")
            top_trace = sorted(candidates, key=lambda candidate: (candidate.relevance_score, candidate.vision_best_frame_score), reverse=True)[:10]
            print(f"Trace scene {scene.scene_id} top rejected candidates:")
            for candidate in top_trace:
                stage = rejection_stage_for(candidate, plan, scene, config)
                reason = candidate.rejection_reason or candidate.duplicate_reason or candidate.validation_note
                print(f"- {candidate.source} {candidate.source_asset_id or candidate.source_page_url} score={candidate.relevance_score} vision={candidate.vision_best_frame_score} stage={stage} reason={reason}")
        report_rows.append(report_row_for(scene, plan, selected, local_file, match_value, rejection_reason, len(candidates), selection_reason, top_rejected))
        print(
            f"Timing {scene.scene_id}: search={search_elapsed:.2f}s "
            f"validation={validation_elapsed:.2f}s download={download_elapsed:.2f}s "
            f"total={time.perf_counter() - scene_started:.2f}s"
        )
        if profile_scene and performance_profile(config):
            print_performance_profile(scene.scene_id, performance_profile(config))
        update_repetition_state(plan, used)
        previous_shots.append(plan.recommended_shot)
        previous_shots = previous_shots[-5:]

    manifest_errors = validate_manifest_integrity(manifest_rows, config)
    if manifest_errors:
        raise RuntimeError("Manifest integrity validation failed: " + " | ".join(manifest_errors[:10]))
    write_manifest(manifest_path, manifest_rows)
    if bool(config.get("enable_vision_cache", True)) and bool(config.get("_vision_cache_dirty", False)):
        save_vision_cache(vision_cache_path, config.get("_vision_cache", {}))
    write_candidate_diagnostics(candidate_diagnostics_path, candidate_diagnostic_rows_out)
    write_visual_director_report(director_report_path, report_rows)
    write_collection_report(collection_report_path, stats, config, dry_run, enabled_sources)
    print(f"Updated manifest: {manifest_path}")
    print(f"Created candidate diagnostics: {candidate_diagnostics_path}")
    print(f"Created visual director report: {director_report_path}")
    print(f"Created collection report: {collection_report_path}")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Visual Director and story-aware B-roll collector for Senior Health AI projects.")
    parser.add_argument("--project", required=True, help="Project folder, for example Projects/<topic_slug>")
    parser.add_argument("--dry-run", action="store_true", help="Analyze and create reports without downloading files.")
    parser.add_argument("--download", action="store_true", help="Download only approved matches above the relevance threshold.")
    parser.add_argument("--scene-id", help="Analyze one scene ID only, for example S042.")
    parser.add_argument("--min-score", type=int, help="Override minimum relevance score for approved downloads.")
    parser.add_argument("--source", action="append", choices=["pexels", "pixabay"], help="Limit source. Repeat for multiple sources.")
    parser.add_argument("--report-only", action="store_true", help="Create Visual Director reports without live stock searches.")
    parser.add_argument("--force", action="store_true", help="Allow replacement or duplicate URL reuse when intentionally rerunning.")
    parser.add_argument("--show-candidates", action="store_true", help="Include top rejected candidate details in reports.")
    parser.add_argument("--candidate-limit", type=int, help="Override candidate pool size per source search.")
    parser.add_argument("--validate-only", action="store_true", help="Validate production scenes and write reports without live searches or downloads.")
    parser.add_argument("--fast-download", action="store_true", help="Use production download optimizations: 1080p preference, small candidate pool, one asset per scene, and skip completed scenes.")
    parser.add_argument("--trace-scene", help="Run a dry-run diagnostic for one scene ID, persist candidate diagnostics, and print stage counts.")
    parser.add_argument("--profile-scene", help="Run a dry-run performance profile for one scene ID and print per-stage timings.")
    parser.add_argument("--profile-fast", help="Run a fast one-scene performance profile with candidate pool 3, max 2 vision requests, and no downloads.")
    args = parser.parse_args()

    if args.dry_run and args.download:
        parser.error("Use either --dry-run or --download, not both.")

    project = Path(args.project)
    if not project.is_absolute():
        project = ROOT / project
    dry_run: bool | None
    if args.trace_scene or args.profile_scene or args.profile_fast:
        dry_run = True
    elif args.download:
        dry_run = False
    elif args.dry_run:
        dry_run = True
    else:
        dry_run = None

    collect_broll(
        project,
        dry_run=dry_run,
        scene_id=args.profile_fast or args.profile_scene or args.trace_scene or args.scene_id,
        min_score=args.min_score,
        sources=args.source,
        report_only=args.report_only,
        force=args.force,
        show_candidates=args.show_candidates,
        candidate_limit=args.candidate_limit,
        validate_only=args.validate_only,
        fast_download=args.fast_download,
        trace_scene=bool(args.trace_scene),
        profile_scene=bool(args.profile_scene),
        profile_fast=bool(args.profile_fast),
    )


if __name__ == "__main__":
    main()
