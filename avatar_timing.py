from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable

from csv_safety import protect_csv_row, validate_script_text

SUPPORTED_AVATAR_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mp3", ".m4a", ".wav"}
SCENE_FILE_RE = re.compile(r"^S(?P<scene>\d+)(?:[_-]avatar)?$", re.I)
CHUNK_FILE_RE = re.compile(r"^c(?P<chunk>\d+)$", re.I)
SAFE_TRANSCRIPTION_MODEL = "whisper-1"
TRANSCRIPTION_RESPONSE_FORMAT = "verbose_json"
TRANSCRIPTION_TIMESTAMP_GRANULARITIES = ("segment", "word")
SUPPORTED_TIMESTAMP_MODELS = {"whisper-1"}
DIRECT_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav"}
DEFAULT_UPLOAD_THRESHOLD_MIB = 24.0
DEFAULT_AUDIO_BITRATE_KBPS = 48
DEFAULT_DURATION_TOLERANCE_SECONDS = 0.25

TIMELINE_COLUMNS = [
    "Scene ID", "Script Text", "Actual Audio Start", "Actual Audio End",
    "Duration", "Avatar Chunk", "Timing Source",
]


@dataclass
class AvatarChunk:
    path: Path
    logical_id: str
    order: int
    naming: str
    scene_id: str | None = None


@dataclass
class ChunkDiscovery:
    chunks: list[AvatarChunk]
    unsupported: list[str]
    duplicates: list[str]


@dataclass(frozen=True)
class ChunkSequenceInfo:
    detected_count: int
    first_chunk: str | None
    last_chunk: str | None
    expected_count: int
    missing_numbers: list[int]


@dataclass
class TranscriptionSummary:
    success: bool
    transcribed: int
    reused: int
    skipped: int
    failures: list[str]
    transcript_dir: Path
    manifest_entries: list[dict[str, Any]]


@dataclass
class AvatarTranscriptionError(RuntimeError):
    def __init__(self, message: str, *, chunk: Path | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.chunk = chunk
        self.details = details or {}


@dataclass
class PreparedMedia:
    upload_path: Path
    extracted: bool
    source_size: int
    upload_size: int
    source_duration: float
    extracted_duration: float
    extraction_settings: dict[str, Any]


@dataclass
class TimelineSummary:
    success: bool
    timeline_path: Path
    manifest_path: Path
    report_path: Path
    alignment_score: float
    warnings: list[str]
    missing_chunks: list[str]
    duplicate_chunks: list[str]
    rows: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tokens(text: str) -> list[str]:
    return [token.lower().replace("’", "'") for token in re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?", text)]


def _seconds_to_timestamp(seconds: float, *, srt: bool = False) -> str:
    # Round once at the final serialized precision, then derive every clock
    # component from the rounded integer total. This makes millisecond carries
    # propagate through seconds/minutes/hours instead of allowing :60.xxx.
    total_millis = int(round(max(0.0, float(seconds)) * 1000))
    hours, remainder = divmod(total_millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1_000)
    separator = "," if srt else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def file_fingerprint(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest.hexdigest()}


def discover_avatar_chunks(folder: Path) -> ChunkDiscovery:
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        return ChunkDiscovery([], [], [])
    scene_candidates: dict[int, list[Path]] = {}
    generic_candidates: dict[int, list[Path]] = {}
    unsupported: list[str] = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_AVATAR_EXTENSIONS:
            unsupported.append(path.name)
            continue
        scene_match = SCENE_FILE_RE.fullmatch(path.stem)
        chunk_match = CHUNK_FILE_RE.fullmatch(path.stem)
        if scene_match:
            scene_candidates.setdefault(int(scene_match.group("scene")), []).append(path)
        elif chunk_match:
            generic_candidates.setdefault(int(chunk_match.group("chunk")), []).append(path)
        else:
            unsupported.append(path.name)

    chunks: list[AvatarChunk] = []
    duplicates: list[str] = []
    if scene_candidates:
        for scene_number in sorted(scene_candidates):
            candidates = scene_candidates[scene_number]
            chosen = sorted(candidates, key=lambda p: p.name.lower())[0]
            if len(candidates) > 1:
                duplicates.append(f"S{scene_number:03d}: " + ", ".join(p.name for p in candidates))
            chunks.append(AvatarChunk(chosen, f"S{scene_number:03d}", scene_number, "scene", f"S{scene_number:03d}"))
        # Scene naming is preferred. Generic files are reported as duplicates/alternatives.
        for number, candidates in sorted(generic_candidates.items()):
            duplicates.append(f"c{number}: ignored because scene-based avatar files are present ({', '.join(p.name for p in candidates)})")
    else:
        for number in sorted(generic_candidates):
            candidates = generic_candidates[number]
            chosen = sorted(candidates, key=lambda p: p.name.lower())[0]
            if len(candidates) > 1:
                duplicates.append(f"c{number}: " + ", ".join(p.name for p in candidates))
            chunks.append(AvatarChunk(chosen, f"c{number}", number, "chunk"))
    return ChunkDiscovery(chunks, unsupported, duplicates)



def chunk_sequence_info(discovery: ChunkDiscovery | None) -> ChunkSequenceInfo:
    """Describe the detected avatar sequence without consulting production scenes.

    Generic HeyGen chunks use a contiguous c1..cN contract. Legacy scene-based
    names remain supported, but their scene numbers are not treated as a required
    contiguous chunk count because they identify production scenes, not chunk slots.
    """
    if discovery is None or not discovery.chunks:
        return ChunkSequenceInfo(0, None, None, 0, [])
    chunks = sorted(discovery.chunks, key=lambda item: item.order)
    if chunks[0].naming == "chunk":
        present = {chunk.order for chunk in chunks}
        last = max(present)
        missing = sorted(set(range(1, last + 1)) - present)
        return ChunkSequenceInfo(len(chunks), chunks[0].path.name, chunks[-1].path.name, last, missing)
    return ChunkSequenceInfo(len(chunks), chunks[0].path.name, chunks[-1].path.name, len(chunks), [])


def transcript_inventory(chunks: Iterable[AvatarChunk], transcript_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    current = 0
    total_duration = 0.0
    for chunk in chunks:
        if not transcript_cache_is_current(chunk, transcript_dir, config):
            continue
        try:
            payload = json.loads((transcript_dir / f"{chunk.path.stem}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        current += 1
        total_duration += _duration_from_payload(payload)
    return {"current": current, "total_duration": total_duration}


def avatar_sync_blockers(lock_ready: bool, avatar_folder: Path, scenes: list[dict[str, str]], discovery: ChunkDiscovery | None) -> list[str]:
    reasons: list[str] = []
    if not lock_ready:
        reasons.append("Production Lock must be READY.")
    if not avatar_folder.is_dir():
        reasons.append("Select an existing Avatar folder.")
    if discovery is not None and not discovery.chunks:
        reasons.append("No supported avatar chunks were found.")
    sequence = chunk_sequence_info(discovery)
    if sequence.missing_numbers:
        labels = ", ".join(f"c{number}" for number in sequence.missing_numbers)
        reasons.append(f"Missing sequential avatar chunks: {labels}.")
    if not scenes:
        reasons.append("07_production_sheet.csv is required before timing alignment.")
    return reasons


def transcription_settings(config: dict[str, Any]) -> dict[str, Any]:
    configured = str(config.get("avatar_transcription_model") or "").strip() or SAFE_TRANSCRIPTION_MODEL
    effective = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "").strip() or configured or SAFE_TRANSCRIPTION_MODEL
    language_value = config.get("avatar_transcription_language")
    language = str(language_value).strip() if language_value else None
    return {
        "configured_model": configured,
        "effective_model": effective,
        "model_source": "OPENAI_TRANSCRIPTION_MODEL" if os.getenv("OPENAI_TRANSCRIPTION_MODEL", "").strip() else ("config.json" if config.get("avatar_transcription_model") else "safe default"),
        "response_format": TRANSCRIPTION_RESPONSE_FORMAT,
        "timestamp_granularities": list(TRANSCRIPTION_TIMESTAMP_GRANULARITIES),
        "timestamp_mode": "segment + word",
        "language": language,
        "word_timing_available": effective in SUPPORTED_TIMESTAMP_MODELS,
    }


def validate_transcription_capabilities(settings: dict[str, Any]) -> None:
    model = str(settings.get("effective_model") or SAFE_TRANSCRIPTION_MODEL)
    missing: list[str] = []
    if model not in SUPPORTED_TIMESTAMP_MODELS:
        missing.extend(["verbose_json response format", "segment timestamps", "word-level timestamps"])
    if missing:
        raise RuntimeError(
            f"Configured transcription model '{model}' is incompatible with Avatar Timing Sync: "
            + ", ".join(missing)
            + f". Recommended compatible model: {SAFE_TRANSCRIPTION_MODEL}."
        )


def transcription_cache_settings(config: dict[str, Any]) -> dict[str, Any]:
    settings = transcription_settings(config)
    return {
        "model": settings["effective_model"],
        "response_format": settings["response_format"],
        "timestamp_granularities": settings["timestamp_granularities"],
        "language": settings["language"],
    }


def _config_float(config: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(config.get(key, default))
    except (TypeError, ValueError):
        return default


def _config_bool(config: dict[str, Any], key: str, default: bool = False) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def media_duration(path: Path) -> float:
    command = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        return float(result.stdout.strip())
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        message = getattr(exc, "stderr", "") or str(exc)
        raise RuntimeError(f"Could not read media duration for {path.name}: {message.strip()}") from exc


def validate_output_directory(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    probe = output_dir / ".avatar_timing_write_test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise RuntimeError(f"Output directory is not writable: {output_dir}") from exc


def preflight_avatar_chunk(chunk: AvatarChunk, transcript_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    path = chunk.path
    settings = transcription_settings(config)
    validate_transcription_capabilities(settings)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Avatar chunk does not exist: {path}")
    if path.suffix.lower() not in SUPPORTED_AVATAR_EXTENSIONS:
        raise RuntimeError(f"Unsupported avatar extension: {path.suffix or '(none)'}")
    try:
        with path.open("rb") as handle:
            handle.read(1)
    except OSError as exc:
        raise RuntimeError(f"Avatar chunk is not readable: {path}") from exc
    validate_output_directory(transcript_dir)
    key_name = str(config.get("openai_api_key_env", "OPENAI_API_KEY"))
    api_key_present = bool(os.getenv(key_name))
    if not api_key_present:
        raise RuntimeError(f"{key_name} is not configured.")
    size = path.stat().st_size
    threshold = int(_config_float(config, "avatar_transcription_upload_threshold_mib", DEFAULT_UPLOAD_THRESHOLD_MIB) * 1024 * 1024)
    direct_safe = path.suffix.lower() in DIRECT_AUDIO_EXTENSIONS and size <= threshold
    return {
        "chunk": path.name, "size_bytes": size, "size_mb": round(size / 1_000_000, 2),
        "status": "Ready for direct upload" if direct_safe else "Requires audio extraction",
        "action": "Upload audio directly" if direct_safe else "Convert before upload",
        "api_key_detected": api_key_present, "settings": settings,
    }


def preflight_avatar_chunks(chunks: Iterable[AvatarChunk], transcript_dir: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for chunk in chunks:
        try:
            rows.append(preflight_avatar_chunk(chunk, transcript_dir, config))
        except Exception as exc:
            size = chunk.path.stat().st_size if chunk.path.exists() else 0
            rows.append({
                "chunk": chunk.path.name, "size_bytes": size, "size_mb": round(size / 1_000_000, 2),
                "status": f"Blocked: {type(exc).__name__}", "action": str(exc),
                "api_key_detected": bool(os.getenv(str(config.get("openai_api_key_env", "OPENAI_API_KEY")))),
                "settings": transcription_settings(config),
            })
    return rows


def prepare_transcription_media(path: Path, transcript_dir: Path, config: dict[str, Any]) -> PreparedMedia:
    source_size = path.stat().st_size
    threshold = int(_config_float(config, "avatar_transcription_upload_threshold_mib", DEFAULT_UPLOAD_THRESHOLD_MIB) * 1024 * 1024)
    if path.suffix.lower() in DIRECT_AUDIO_EXTENSIONS and source_size <= threshold:
        duration = media_duration(path)
        return PreparedMedia(path, False, source_size, source_size, duration, duration, {"mode": "direct"})
    if not ffmpeg_available():
        raise RuntimeError(
            "ffmpeg and ffprobe are required to prepare large avatar videos. "
            "Install FFmpeg and ensure both commands are available on PATH."
        )
    temp_dir = transcript_dir / "_temp_audio"
    validate_output_directory(temp_dir)
    bitrate = int(_config_float(config, "avatar_transcription_audio_bitrate_kbps", DEFAULT_AUDIO_BITRATE_KBPS))
    output = temp_dir / f"{path.stem}_transcription_audio.mp3"
    source_duration = media_duration(path)
    command = [
        "ffmpeg", "-y", "-v", "error", "-i", str(path), "-map", "0:a:0",
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", f"{bitrate}k", str(output),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        message = getattr(exc, "stderr", "") or str(exc)
        raise RuntimeError(f"ffmpeg audio extraction failed for {path.name}: {message.strip()}") from exc
    extracted_duration = media_duration(output)
    tolerance = _config_float(config, "avatar_transcription_duration_tolerance_seconds", DEFAULT_DURATION_TOLERANCE_SECONDS)
    if abs(source_duration - extracted_duration) > tolerance:
        raise RuntimeError(
            f"Audio duration mismatch for {path.name}: source={source_duration:.3f}s, "
            f"extracted={extracted_duration:.3f}s, tolerance={tolerance:.3f}s."
        )
    upload_size = output.stat().st_size
    if upload_size > threshold:
        raise RuntimeError(
            f"Prepared audio is {upload_size / 1024 / 1024:.2f} MiB, above the configured "
            f"upload threshold of {threshold / 1024 / 1024:.2f} MiB."
        )
    return PreparedMedia(output, True, source_size, upload_size, source_duration, extracted_duration, {
        "format": "mp3", "codec": "libmp3lame", "bitrate_kbps": bitrate, "channels": 1, "sample_rate_hz": 16000,
    })


def _response_to_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    for method in ("model_dump", "to_dict"):
        fn = getattr(response, method, None)
        if callable(fn):
            value = fn()
            if isinstance(value, dict):
                return value
    try:
        return json.loads(str(response))
    except (TypeError, json.JSONDecodeError):
        return {"text": str(response)}


def openai_transcribe_avatar(path: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Use OpenAI's transcription API and request segment + word timestamps.

    Import is intentionally lazy so the rest of the application remains usable when
    transcription dependencies or credentials are not configured.
    """
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as exc:
        raise RuntimeError("OpenAI Python package is not installed. Install project requirements first.") from exc
    api_key = os.getenv(str(config.get("openai_api_key_env", "OPENAI_API_KEY")))
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    client = OpenAI(api_key=api_key)
    settings = transcription_settings(config)
    validate_transcription_capabilities(settings)
    model = str(settings["effective_model"])
    request: dict[str, Any] = {
        "model": model,
        "response_format": settings["response_format"],
        "timestamp_granularities": settings["timestamp_granularities"],
    }
    if settings.get("language"):
        request["language"] = settings["language"]
    with path.open("rb") as media:
        response = client.audio.transcriptions.create(file=media, **request)
    payload = _response_to_dict(response)
    payload.setdefault("model", model)
    payload.setdefault("source_filename", path.name)
    return payload


def _write_srt(payload: dict[str, Any], path: Path) -> None:
    segments = payload.get("segments") or []
    entries: list[str] = []
    for index, segment in enumerate(segments, 1):
        if not isinstance(segment, dict):
            continue
        start = float(segment.get("start", 0.0) or 0.0)
        end = float(segment.get("end", start) or start)
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        entries.append(f"{index}\n{_seconds_to_timestamp(start, srt=True)} --> {_seconds_to_timestamp(end, srt=True)}\n{text}\n")
    if not entries and str(payload.get("text", "")).strip():
        duration = float(payload.get("duration", 0.0) or 0.0)
        entries.append(f"1\n00:00:00,000 --> {_seconds_to_timestamp(duration, srt=True)}\n{str(payload['text']).strip()}\n")
    path.write_text("\n".join(entries), encoding="utf-8", newline="\n")


def _duration_from_payload(payload: dict[str, Any]) -> float:
    if payload.get("duration") is not None:
        try:
            return max(0.0, float(payload["duration"]))
        except (TypeError, ValueError):
            pass
    words = payload.get("words") or []
    segments = payload.get("segments") or []
    endings = []
    for item in list(words) + list(segments):
        if isinstance(item, dict) and item.get("end") is not None:
            try:
                endings.append(float(item["end"]))
            except (TypeError, ValueError):
                pass
    return max(endings, default=0.0)


def transcribe_avatar_chunks(
    chunks: Iterable[AvatarChunk],
    transcript_dir: Path,
    config: dict[str, Any],
    *,
    transcriber: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
    progress: Callable[[str], None] | None = None,
) -> TranscriptionSummary:
    transcript_dir.mkdir(parents=True, exist_ok=True)
    use_default_transcriber = transcriber is None
    transcriber = transcriber or openai_transcribe_avatar
    transcribed = reused = skipped = 0
    failures: list[str] = []
    entries: list[dict[str, Any]] = []
    cache_settings = transcription_cache_settings(config)
    validate_transcription_capabilities(transcription_settings(config))
    for chunk in chunks:
        if progress:
            progress(f"Preparing {chunk.path.name}...")
        json_path = transcript_dir / f"{chunk.path.stem}.json"
        srt_path = transcript_dir / f"{chunk.path.stem}.srt"
        fingerprint = file_fingerprint(chunk.path)
        prepared: PreparedMedia | None = None
        extraction_settings = {"mode": "test/custom transcriber"}
        cached: dict[str, Any] = {}
        if json_path.exists():
            try:
                cached = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cached = {}
        cache_meta = cached.get("_avatar_timing", {})
        expected_settings = dict(cache_settings)
        if use_default_transcriber:
            expected_settings["extraction"] = {
                "format": "mp3",
                "bitrate_kbps": int(_config_float(config, "avatar_transcription_audio_bitrate_kbps", DEFAULT_AUDIO_BITRATE_KBPS)),
                "channels": 1, "sample_rate_hz": 16000,
                "upload_threshold_mib": _config_float(config, "avatar_transcription_upload_threshold_mib", DEFAULT_UPLOAD_THRESHOLD_MIB),
            }
        if cache_meta.get("fingerprint") == fingerprint and cache_meta.get("transcription_settings") == expected_settings and srt_path.exists():
            payload = cached
            reused += 1
            status = "REUSED"
        else:
            try:
                upload_path = chunk.path
                if use_default_transcriber:
                    preflight_avatar_chunk(chunk, transcript_dir, config)
                    if progress:
                        progress("Extracting audio...")
                    prepared = prepare_transcription_media(chunk.path, transcript_dir, config)
                    upload_path = prepared.upload_path
                    extraction_settings = prepared.extraction_settings
                if progress:
                    progress("Uploading transcription audio...")
                payload = transcriber(upload_path, config)
                if not isinstance(payload, dict) or not str(payload.get("text", "")).strip():
                    raise RuntimeError("Transcription returned no text.")
                payload["_avatar_timing"] = {
                    "fingerprint": fingerprint, "source_filename": chunk.path.name, "transcribed_at": _utc_now(),
                    "transcription_settings": expected_settings,
                    "extracted_audio_settings": extraction_settings,
                    "extracted_audio_size": prepared.upload_size if prepared else chunk.path.stat().st_size,
                    "source_duration": prepared.source_duration if prepared else _duration_from_payload(payload),
                    "extracted_duration": prepared.extracted_duration if prepared else _duration_from_payload(payload),
                }
                if progress:
                    progress(f"Saving {json_path.name}...")
                json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
                if progress:
                    progress(f"Saving {srt_path.name}...")
                _write_srt(payload, srt_path)
                if prepared and prepared.extracted and not _config_bool(config, "avatar_transcription_keep_temp_audio", False):
                    prepared.upload_path.unlink(missing_ok=True)
                transcribed += 1
                status = "TRANSCRIBED"
                if progress:
                    progress(f"Completed {chunk.path.name}")
            except Exception as exc:
                skipped += 1
                details = {
                    "failed_chunk": chunk.path.name, "file_size_mb": round(chunk.path.stat().st_size / 1_000_000, 2) if chunk.path.exists() else None,
                    "output_directory": str(transcript_dir), **transcription_settings(config),
                    "api_key_detected": bool(os.getenv(str(config.get("openai_api_key_env", "OPENAI_API_KEY")))),
                }
                raise AvatarTranscriptionError(str(exc), chunk=chunk.path, details=details) from exc
        entries.append({
            "chunk_filename": chunk.path.name, "logical_id": chunk.logical_id,
            "duration": round(_duration_from_payload(payload), 3), "transcript_status": status,
            "json_file": json_path.name, "srt_file": srt_path.name, "fingerprint": fingerprint,
            "word_timing_available": bool(payload.get("words")), "transcription_model": cache_settings["model"],
            "response_format": cache_settings["response_format"], "timestamp_granularities": cache_settings["timestamp_granularities"],
            "language": cache_settings["language"],
        })
    return TranscriptionSummary(not failures, transcribed, reused, skipped, failures, transcript_dir, entries)


def _expected_transcript_cache_settings(
    config: dict[str, Any], *, include_extraction: bool
) -> dict[str, Any]:
    expected = transcription_cache_settings(config)
    if include_extraction:
        expected["extraction"] = {
            "format": "mp3",
            "bitrate_kbps": int(_config_float(config, "avatar_transcription_audio_bitrate_kbps", DEFAULT_AUDIO_BITRATE_KBPS)),
            "channels": 1, "sample_rate_hz": 16000,
            "upload_threshold_mib": _config_float(config, "avatar_transcription_upload_threshold_mib", DEFAULT_UPLOAD_THRESHOLD_MIB),
        }
    return expected


def _transcript_cache_validation_failure(
    chunk: AvatarChunk,
    transcript_dir: Path,
    config: dict[str, Any],
    *,
    payload: dict[str, Any] | None = None,
) -> str | None:
    json_path = transcript_dir / f"{chunk.path.stem}.json"
    srt_path = transcript_dir / f"{chunk.path.stem}.srt"
    if not json_path.is_file() or not srt_path.is_file():
        return "missing transcript cache files"
    if payload is None:
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "invalid transcript cache JSON"
    metadata = payload.get("_avatar_timing", {})
    if metadata.get("fingerprint") != file_fingerprint(chunk.path):
        return "media changed; re-transcription required"
    stored_settings = metadata.get("transcription_settings")
    expected_settings = _expected_transcript_cache_settings(
        config,
        include_extraction=isinstance(stored_settings, dict) and "extraction" in stored_settings,
    )
    if stored_settings != expected_settings:
        return "transcription model/settings changed; re-transcription required"
    return None


def transcript_cache_is_current(chunk: AvatarChunk, transcript_dir: Path, config: dict[str, Any]) -> bool:
    return _transcript_cache_validation_failure(chunk, transcript_dir, config) is None


def load_production_scenes(sheet_path: Path) -> list[dict[str, str]]:
    if not sheet_path.is_file():
        return []
    with sheet_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    scenes: list[dict[str, str]] = []
    for index, row in enumerate(rows, 1):
        scene_id = str(row.get("scene_id") or row.get("Scene ID") or f"S{index:03d}").strip()
        raw_script = row.get("script_excerpt") or row.get("Script Text") or row.get("narration") or ""
        try:
            script = validate_script_text(raw_script, scene_id).strip()
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        if scene_id and script:
            scenes.append({"scene_id": scene_id, "script_text": script})
    return scenes


def expected_avatar_chunks(scenes: list[dict[str, str]], sheet_path: Path) -> list[str]:
    if not sheet_path.is_file():
        return []
    with sheet_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected: list[str] = []
    for index, row in enumerate(rows, 1):
        avatar_value = str(row.get("avatar_required") or "").strip().upper()
        visual_mode = str(row.get("visual_mode") or row.get("recommended_asset_type") or "").strip().upper()
        if avatar_value in {"YES", "TRUE", "1", "REQUIRED"} or visual_mode == "AVATAR":
            expected.append(str(row.get("scene_id") or f"S{index:03d}").strip())
    return expected or [scene["scene_id"] for scene in scenes]


def _load_transcript_payloads(chunks: list[AvatarChunk], transcript_dir: Path, config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    payloads: list[dict[str, Any]] = []
    failures: list[str] = []
    offset = 0.0
    for chunk in chunks:
        path = transcript_dir / f"{chunk.path.stem}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            failures.append(chunk.path.name)
            continue
        cache_failure = _transcript_cache_validation_failure(
            chunk, transcript_dir, config, payload=payload
        )
        if cache_failure:
            failures.append(f"{chunk.path.name} ({cache_failure})")
            continue
        duration = _duration_from_payload(payload)
        words = payload.get("words") or []
        normalized_words: list[dict[str, Any]] = []
        if words:
            for item in words:
                if not isinstance(item, dict):
                    continue
                word = str(item.get("word") or item.get("text") or "").strip()
                if not word:
                    continue
                normalized_words.append({
                    "word": word,
                    "start": offset + float(item.get("start", 0.0) or 0.0),
                    "end": offset + float(item.get("end", item.get("start", 0.0)) or 0.0),
                    "chunk": chunk.path.name,
                })
        if not normalized_words:
            text_tokens = _tokens(str(payload.get("text", "")))
            step = duration / max(1, len(text_tokens))
            normalized_words = [
                {"word": word, "start": offset + i * step, "end": offset + (i + 1) * step, "chunk": chunk.path.name}
                for i, word in enumerate(text_tokens)
            ]
        normalized_segments: list[dict[str, Any]] = []
        for item in payload.get("segments") or []:
            if not isinstance(item, dict):
                continue
            normalized_segments.append({
                **item,
                "start": offset + float(item.get("start", 0.0) or 0.0),
                "end": offset + float(item.get("end", item.get("start", 0.0)) or 0.0),
                "chunk": chunk.path.name,
            })
        payloads.append({
            "chunk": chunk, "payload": payload, "words": normalized_words,
            "segments": normalized_segments, "offset": offset, "duration": duration,
        })
        offset += duration
    return payloads, failures


def _alignment_map(approved_tokens: list[str], transcript_tokens: list[str]) -> tuple[dict[int, int], float]:
    matcher = SequenceMatcher(None, approved_tokens, transcript_tokens, autojunk=False)
    mapping: dict[int, int] = {}
    matched = 0
    for block in matcher.get_matching_blocks():
        for delta in range(block.size):
            mapping[block.a + delta] = block.b + delta
        matched += block.size
    score = (2.0 * matched / max(1, len(approved_tokens) + len(transcript_tokens))) * 100.0
    return mapping, round(score, 1)


def _nearest_mapping(mapping: dict[int, int], approved_index: int, *, forward: bool) -> int | None:
    if approved_index in mapping:
        return mapping[approved_index]
    keys = sorted(mapping)
    candidates = [key for key in keys if key >= approved_index] if forward else [key for key in keys if key <= approved_index]
    if not candidates:
        return None
    key = candidates[0] if forward else candidates[-1]
    return mapping[key]


def _project_aligned_index(mapping: dict[int, int], source_index: int, target_length: int) -> int | None:
    """Project an unmatched source token through surrounding monotonic anchors.

    SequenceMatcher only maps equal-token blocks. Scene boundaries can fall in a
    replace/insert block, so use the closest anchors on both sides rather than
    starting another local greedy search.
    """
    if not mapping or target_length <= 0:
        return None
    if source_index in mapping:
        return mapping[source_index]
    keys = sorted(mapping)
    left = next((key for key in reversed(keys) if key < source_index), None)
    right = next((key for key in keys if key > source_index), None)
    if left is not None and right is not None:
        source_span = right - left
        target_span = mapping[right] - mapping[left]
        ratio = (source_index - left) / source_span
        projected = mapping[left] + round(ratio * target_span)
    elif left is not None:
        projected = mapping[left] + (source_index - left)
    elif right is not None:
        projected = mapping[right] - (right - source_index)
    else:
        return None
    return max(0, min(target_length - 1, projected))


def _scene_approved_spans(
    scenes: list[dict[str, str]], approved_tokens: list[str]
) -> list[tuple[dict[str, str], int, int]]:
    """Align all production narration to the approved script in one pass.

    A single global alignment keeps repeated or lightly edited scene text
    monotonic. It avoids cumulative cursor drift from independent longest-match
    searches while preserving production scene order.
    """
    production_tokens: list[str] = []
    scene_ranges: list[tuple[dict[str, str], int, int]] = []
    for scene in scenes:
        scene_tokens = _tokens(scene["script_text"])
        if not scene_tokens:
            continue
        start = len(production_tokens)
        production_tokens.extend(scene_tokens)
        scene_ranges.append((scene, start, len(production_tokens) - 1))

    if not production_tokens or not approved_tokens:
        return []

    production_to_approved, _ = _alignment_map(production_tokens, approved_tokens)
    spans: list[tuple[dict[str, str], int, int]] = []
    previous_end = -1
    for scene, production_start, production_end in scene_ranges:
        scene_anchors = [
            production_to_approved[index]
            for index in range(production_start, production_end + 1)
            if index in production_to_approved
        ]
        if scene_anchors:
            approved_start = min(scene_anchors)
            approved_end = max(scene_anchors)
        else:
            approved_start = _project_aligned_index(
                production_to_approved, production_start, len(approved_tokens)
            )
            approved_end = _project_aligned_index(
                production_to_approved, production_end, len(approved_tokens)
            )
        if approved_start is None or approved_end is None:
            continue
        approved_start = max(previous_end + 1, approved_start)
        approved_start = min(approved_start, len(approved_tokens) - 1)
        approved_end = max(approved_start, approved_end)
        approved_end = min(approved_end, len(approved_tokens) - 1)
        spans.append((scene, approved_start, approved_end))
        previous_end = approved_end
    return spans



def _resolve_scene_word_ranges(
    raw_ranges: list[tuple[dict[str, str], int, int]], transcript_word_count: int
) -> list[tuple[dict[str, str], int, int]]:
    """Resolve scene ranges into positive, monotonic, non-overlapping word spans.

    Scene alignment can project two adjacent boundaries onto the same transcript
    word. Assigning ranges globally lets the later scene move to the next actual
    transcript word timestamp instead of emitting a zero-duration row. No timing
    is synthesized: every boundary comes from an existing word start or end.
    """
    if not raw_ranges:
        return []
    if transcript_word_count < len(raw_ranges):
        raise RuntimeError(
            "Cannot assign positive transcript timing to every narrated scene: "
            f"{len(raw_ranges)} scenes but only {transcript_word_count} timed words."
        )

    starts: list[int] = []
    previous_start = -1
    scene_count = len(raw_ranges)
    for index, (_scene, candidate_start, _candidate_end) in enumerate(raw_ranges):
        remaining_scenes = scene_count - index - 1
        latest_start = transcript_word_count - remaining_scenes - 1
        resolved_start = max(previous_start + 1, min(candidate_start, latest_start))
        starts.append(resolved_start)
        previous_start = resolved_start

    resolved: list[tuple[dict[str, str], int, int]] = []
    for index, (scene, _candidate_start, candidate_end) in enumerate(raw_ranges):
        start_index = starts[index]
        if index + 1 < scene_count:
            # The next scene owns its start word, so this scene must finish on
            # the immediately preceding real transcript word.
            end_index = starts[index + 1] - 1
        else:
            end_index = max(start_index, min(candidate_end, transcript_word_count - 1))
        if end_index < start_index:
            raise RuntimeError(
                f"Scene {scene['scene_id']} could not be assigned a positive transcript word range."
            )
        resolved.append((scene, start_index, end_index))
    return resolved

def build_actual_timeline(
    project: Path,
    avatar_folder: Path,
    config: dict[str, Any],
    *,
    transcript_dir: Path | None = None,
) -> TimelineSummary:
    project = project.resolve()
    discovery = discover_avatar_chunks(avatar_folder)
    transcript_dir = transcript_dir or project / "avatar_transcripts"
    timeline_path = project / "08_actual_timeline.csv"
    manifest_path = project / "avatar_timing_manifest.json"
    report_path = project / "avatar_alignment_report.md"
    warnings: list[str] = []
    missing: list[str] = []
    scenes = load_production_scenes(project / "07_production_sheet.csv")
    sequence = chunk_sequence_info(discovery)
    if not discovery.chunks:
        missing.append("No supported avatar chunks were found.")
    if not scenes:
        missing.append("07_production_sheet.csv is missing or has no scene narration.")
    missing.extend(f"c{number}" for number in sequence.missing_numbers)

    payloads, transcript_failures = _load_transcript_payloads(discovery.chunks, transcript_dir, config)
    missing.extend(f"Transcript missing: {name}" for name in transcript_failures)
    transcript_words = [word for payload in payloads for word in payload["words"]]
    transcript_tokens = [_tokens(word["word"])[0] for word in transcript_words if _tokens(word["word"])]
    approved_text = (project / "06a_voice_script.md").read_text(encoding="utf-8") if (project / "06a_voice_script.md").is_file() else ""
    approved_tokens = _tokens(approved_text)
    mapping, alignment_score = _alignment_map(approved_tokens, transcript_tokens) if approved_tokens and transcript_tokens else ({}, 0.0)
    threshold = float(config.get("avatar_alignment_threshold", 92.0))
    if alignment_score < threshold:
        warnings.append(f"Alignment score {alignment_score:.1f}% is below the configured {threshold:.1f}% threshold.")

    # Align all production scenes to approved narration once, then resolve all
    # transcript word ranges globally. Resolving ranges as a sequence prevents
    # adjacent scene boundaries from collapsing onto the same transcript word.
    rows: list[dict[str, Any]] = []
    scene_spans = _scene_approved_spans(scenes, approved_tokens)
    aligned_scene_ids = {scene["scene_id"] for scene, _, _ in scene_spans}
    for scene in scenes:
        if _tokens(scene["script_text"]) and scene["scene_id"] not in aligned_scene_ids:
            warnings.append(f"{scene['scene_id']}: timing could not be aligned.")

    raw_ranges: list[tuple[dict[str, str], int, int]] = []
    for scene, scene_start, scene_end in scene_spans:
        transcript_start_index = _nearest_mapping(mapping, scene_start, forward=True)
        transcript_end_index = _nearest_mapping(mapping, scene_end, forward=False)
        if transcript_start_index is None or transcript_end_index is None:
            warnings.append(f"{scene['scene_id']}: timing could not be aligned.")
            continue
        raw_ranges.append((scene, transcript_start_index, transcript_end_index))

    resolved_ranges = _resolve_scene_word_ranges(raw_ranges, len(transcript_words))
    for scene, transcript_start_index, transcript_end_index in resolved_ranges:
        start_seconds = float(transcript_words[transcript_start_index]["start"])
        end_seconds = float(transcript_words[transcript_end_index]["end"])
        duration = end_seconds - start_seconds
        if duration <= 0:
            raise RuntimeError(
                f"Scene {scene['scene_id']} has invalid timeline timing: "
                f"start={_seconds_to_timestamp(start_seconds)}, "
                f"end={_seconds_to_timestamp(end_seconds)}, "
                f"duration={duration:.3f}, text={scene['script_text']}"
            )
        chunk_names = []
        for word in transcript_words[transcript_start_index:transcript_end_index + 1]:
            if word["chunk"] not in chunk_names:
                chunk_names.append(word["chunk"])
        chunk_display = chunk_names[0] if len(chunk_names) == 1 else (
            f"{chunk_names[0]} to {chunk_names[-1]}" if chunk_names else ""
        )
        rows.append({
            "Scene ID": scene["scene_id"],
            "Script Text": scene["script_text"],
            "Actual Audio Start": _seconds_to_timestamp(start_seconds),
            "Actual Audio End": _seconds_to_timestamp(end_seconds),
            "Duration": f"{duration:.3f}",
            "Avatar Chunk": chunk_display,
            "Timing Source": "TRANSCRIPT",
        })

    hard_failures = bool(missing or transcript_failures or not rows)
    success = not hard_failures
    if success:
        with timeline_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=TIMELINE_COLUMNS)
            writer.writeheader()
            writer.writerows(protect_csv_row(row, text_columns={"Scene ID", "Script Text", "Avatar Chunk", "Timing Source"}) for row in rows)

    matched_scene_ids = [row["Scene ID"] for row in rows]
    manifest_entries: list[dict[str, Any]] = []
    for payload in payloads:
        chunk = payload["chunk"]
        chunk_rows = [row for row in rows if chunk.path.name in row["Avatar Chunk"]]
        manifest_entries.append({
            "chunk_filename": chunk.path.name,
            "duration": round(payload["duration"], 3),
            "transcript_status": "SUCCESS",
            "alignment_score": alignment_score,
            "matched_scene_range": (
                f"{chunk_rows[0]['Scene ID']}–{chunk_rows[-1]['Scene ID']}" if chunk_rows else "UNMATCHED"
            ),
            "fingerprint": file_fingerprint(chunk.path),
            "word_timing_available": bool(payload["payload"].get("words")),
            "global_audio_start": round(payload["offset"], 3),
            "global_audio_end": round(payload["offset"] + payload["duration"], 3),
        })
    settings = transcription_settings(config)
    manifest = {
        "version": "3.3",
        "generated_at": _utc_now(),
        "source_script": "06a_voice_script.md",
        "production_sheet": "07_production_sheet.csv",
        "avatar_folder": str(avatar_folder.resolve()),
        "alignment_score": alignment_score,
        "alignment_threshold": threshold,
        "timeline_status": "PASS" if success else "FAIL",
        "transcription_model": settings["effective_model"],
        "configured_transcription_model": settings["configured_model"],
        "transcription_model_source": settings["model_source"],
        "response_format": settings["response_format"],
        "timestamp_granularities": settings["timestamp_granularities"],
        "transcription_language": settings["language"],
        "detected_chunks": sequence.detected_count,
        "expected_sequential_chunks": sequence.expected_count,
        "missing_chunk_numbers": sequence.missing_numbers,
        "total_avatar_duration": round(sum(item["duration"] for item in payloads), 3),
        "total_production_scenes": len(scenes),
        "matched_scenes": matched_scene_ids,
        "chunks": manifest_entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    report_lines = [
        "# Avatar Alignment Report", "", f"**Status:** {'PASS' if success else 'FAIL'}", "",
        f"- Chunks Found: {sequence.detected_count}",
        f"- Chunks Expected: {sequence.expected_count}",
        f"- Detected Chunks: {sequence.detected_count}",
        f"- First Chunk: {sequence.first_chunk or 'None'}",
        f"- Last Chunk: {sequence.last_chunk or 'None'}",
        f"- Expected Sequential Chunks: {sequence.expected_count}",
        f"- Missing Chunk Numbers: {', '.join(map(str, sequence.missing_numbers)) if sequence.missing_numbers else 'None'}",
        f"- Total Avatar Duration: {sum(item['duration'] for item in payloads):.3f} seconds",
        f"- Total Production Scenes: {len(scenes)}",
        f"- Chunks Missing: {len(missing)}",
        f"- Duplicate Chunks: {len(discovery.duplicates)}",
        f"- Alignment %: {alignment_score:.1f}%",
        f"- Transcript Success: {len(payloads)}/{len(discovery.chunks)}",
        f"- Transcription Model: {settings['effective_model']}",
        f"- Model Source: {settings['model_source']}",
        f"- Response Format: {settings['response_format']}",
        f"- Timestamp Mode: {settings['timestamp_mode']}",
        f"- Word Timing Available: {'Yes' if settings['word_timing_available'] else 'No'}",
        f"- Timeline Rows: {len(rows)}", "", "## Missing Chunks",
    ]
    report_lines.extend([f"- {item}" for item in missing] or ["- None"])
    report_lines.extend(["", "## Duplicate Chunks"])
    report_lines.extend([f"- {item}" for item in discovery.duplicates] or ["- None"])
    report_lines.extend(["", "## Unsupported Files"])
    report_lines.extend([f"- {item}" for item in discovery.unsupported] or ["- None"])
    report_lines.extend(["", "## Warnings"])
    report_lines.extend([f"- {item}" for item in warnings] or ["- None"])
    report_lines.append("")
    report_path.write_text("\n".join(report_lines), encoding="utf-8", newline="\n")
    return TimelineSummary(success, timeline_path, manifest_path, report_path, alignment_score, warnings, missing, discovery.duplicates, len(rows))

