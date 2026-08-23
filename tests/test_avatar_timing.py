from __future__ import annotations

import csv
import json
import hashlib
import subprocess

import pytest
from pathlib import Path

from avatar_timing import (
    avatar_sync_blockers,
    AvatarTranscriptionError, build_actual_timeline,
    discover_avatar_chunks, ffmpeg_available, prepare_transcription_media,
    load_production_scenes,
    transcribe_avatar_chunks,
)


def write_sheet(project: Path, scene_ids=("S001", "S002")) -> None:
    rows = [
        {
            "scene_id": scene_id,
            "script_excerpt": text,
            "avatar_required": "YES",
            "visual_mode": "AVATAR",
        }
        for scene_id, text in zip(
            scene_ids,
            (
                "Hello seniors, I am Adrian Westbrook, your Health Educator.",
                "Please talk to your doctor and subscribe for more evidence based education.",
            ),
        )
    ]
    with (project / "07_production_sheet.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scene_id", "script_excerpt", "avatar_required", "visual_mode"])
        writer.writeheader()
        writer.writerows(rows)
    (project / "06a_voice_script.md").write_text(
        " ".join(row["script_excerpt"] for row in rows) + "\n", encoding="utf-8"
    )


def fake_payload(path: Path, _config: dict) -> dict:
    if path.stem.lower().startswith("s001"):
        text = "Hello seniors, I am Adrian Westbrook, your Health Educator."
    else:
        text = "Please talk to your doctor and subscribe for more evidence based education."
    words = text.replace(",", "").replace(".", "").split()
    return {
        "text": text,
        "duration": float(len(words)),
        "segments": [{"start": 0.0, "end": float(len(words)), "text": text}],
        "words": [
            {"word": word, "start": float(index), "end": float(index + 1)}
            for index, word in enumerate(words)
        ],
    }


def setup_project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    avatars = project / "avatars"
    avatars.mkdir(parents=True)
    write_sheet(project)
    (avatars / "S001_avatar.mp4").write_bytes(b"avatar-one")
    (avatars / "S002_avatar.mp4").write_bytes(b"avatar-two")
    return project, avatars


def test_all_avatar_chunks_generate_timeline(tmp_path: Path) -> None:
    project, avatars = setup_project(tmp_path)
    discovery = discover_avatar_chunks(avatars)
    transcription = transcribe_avatar_chunks(discovery.chunks, project / "avatar_transcripts", {}, transcriber=fake_payload)
    assert transcription.success
    assert transcription.transcribed == 2
    result = build_actual_timeline(project, avatars, {"avatar_alignment_threshold": 90})
    assert result.success
    assert result.rows == 2
    assert (project / "08_actual_timeline.csv").is_file()
    assert (project / "avatar_timing_manifest.json").is_file()
    assert (project / "avatar_alignment_report.md").is_file()
    with (project / "08_actual_timeline.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["Timing Source"] == "TRANSCRIPT"
    assert rows[0]["Avatar Chunk"] == "S001_avatar.mp4"


def test_scene_named_chunks_are_not_assumed_one_per_production_scene(tmp_path: Path) -> None:
    project, avatars = setup_project(tmp_path)
    (avatars / "S002_avatar.mp4").unlink()
    discovery = discover_avatar_chunks(avatars)
    transcribe_avatar_chunks(discovery.chunks, project / "avatar_transcripts", {}, transcriber=fake_payload)
    result = build_actual_timeline(project, avatars, {})
    assert "S002" not in result.missing_chunks
    report = (project / "avatar_alignment_report.md").read_text(encoding="utf-8")
    assert "Expected Sequential Chunks: 1" in report
    assert "Total Production Scenes: 2" in report


def test_duplicate_chunk_is_reported_and_scene_name_preferred(tmp_path: Path) -> None:
    project, avatars = setup_project(tmp_path)
    (avatars / "S001_avatar.mov").write_bytes(b"duplicate")
    (avatars / "c1.mp4").write_bytes(b"generic-alternative")
    discovery = discover_avatar_chunks(avatars)
    assert len(discovery.chunks) == 2
    assert all(chunk.naming == "scene" for chunk in discovery.chunks)
    assert discovery.duplicates
    assert any("S001" in item for item in discovery.duplicates)
    assert any("c1" in item for item in discovery.duplicates)


def test_transcription_failure_is_clear(tmp_path: Path) -> None:
    project, avatars = setup_project(tmp_path)
    discovery = discover_avatar_chunks(avatars)

    def failing(path: Path, _config: dict) -> dict:
        if path.name.startswith("S002"):
            raise RuntimeError("service unavailable")
        return fake_payload(path, _config)

    with pytest.raises(AvatarTranscriptionError) as caught:
        transcribe_avatar_chunks(discovery.chunks, project / "avatar_transcripts", {}, transcriber=failing)
    assert caught.value.chunk.name == "S002_avatar.mp4"
    assert "service unavailable" in str(caught.value)
    assert (project / "avatar_transcripts" / "S001_avatar.json").is_file()
    assert (project / "avatar_transcripts" / "S001_avatar.srt").is_file()


def test_low_alignment_generates_warning(tmp_path: Path) -> None:
    project, avatars = setup_project(tmp_path)
    discovery = discover_avatar_chunks(avatars)

    def unrelated(path: Path, _config: dict) -> dict:
        text = "Completely unrelated spoken words with no matching approved narration"
        words = text.split()
        return {
            "text": text,
            "duration": len(words),
            "segments": [{"start": 0, "end": len(words), "text": text}],
            "words": [{"word": word, "start": i, "end": i + 1} for i, word in enumerate(words)],
        }

    transcribe_avatar_chunks(discovery.chunks, project / "avatar_transcripts", {}, transcriber=unrelated)
    result = build_actual_timeline(project, avatars, {"avatar_alignment_threshold": 95})
    assert result.warnings
    assert "below" in result.warnings[0]


def test_production_lock_not_ready_disables_sync(tmp_path: Path) -> None:
    project, avatars = setup_project(tmp_path)
    discovery = discover_avatar_chunks(avatars)
    scenes = load_production_scenes(project / "07_production_sheet.csv")
    blockers = avatar_sync_blockers(False, avatars, scenes, discovery)
    assert "Production Lock must be READY." in blockers


def test_transcription_cache_reuses_unchanged_chunk(tmp_path: Path) -> None:
    project, avatars = setup_project(tmp_path)
    discovery = discover_avatar_chunks(avatars)
    calls = []

    def counted(path: Path, config: dict) -> dict:
        calls.append(path.name)
        return fake_payload(path, config)

    first = transcribe_avatar_chunks(discovery.chunks, project / "avatar_transcripts", {}, transcriber=counted)
    second = transcribe_avatar_chunks(discovery.chunks, project / "avatar_transcripts", {}, transcriber=counted)
    assert first.transcribed == 2
    assert second.reused == 2
    assert len(calls) == 2
    payload = json.loads((project / "avatar_transcripts" / "S001_avatar.json").read_text(encoding="utf-8"))
    assert payload["words"]
    assert payload["_avatar_timing"]["fingerprint"]["sha256"]


def test_environment_model_overrides_config(monkeypatch) -> None:
    from avatar_timing import transcription_settings
    monkeypatch.setenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
    settings = transcription_settings({"avatar_transcription_model": "configured-model"})
    assert settings["effective_model"] == "whisper-1"
    assert settings["configured_model"] == "configured-model"
    assert settings["model_source"] == "OPENAI_TRANSCRIPTION_MODEL"


def test_config_model_used_without_environment(monkeypatch) -> None:
    from avatar_timing import transcription_settings
    monkeypatch.delenv("OPENAI_TRANSCRIPTION_MODEL", raising=False)
    settings = transcription_settings({"avatar_transcription_model": "whisper-1"})
    assert settings["effective_model"] == "whisper-1"
    assert settings["model_source"] == "config.json"


def test_safe_default_used_without_configuration(monkeypatch) -> None:
    from avatar_timing import transcription_settings
    monkeypatch.delenv("OPENAI_TRANSCRIPTION_MODEL", raising=False)
    settings = transcription_settings({})
    assert settings["effective_model"] == "whisper-1"
    assert settings["model_source"] == "safe default"
    assert settings["word_timing_available"] is True


def test_cache_invalidated_when_transcription_model_changes(tmp_path: Path, monkeypatch) -> None:
    project, avatars = setup_project(tmp_path)
    discovery = discover_avatar_chunks(avatars)
    calls = []

    def counted(path: Path, config: dict) -> dict:
        calls.append((path.name, config.get("avatar_transcription_model")))
        return fake_payload(path, config)

    monkeypatch.delenv("OPENAI_TRANSCRIPTION_MODEL", raising=False)
    first = transcribe_avatar_chunks(
        discovery.chunks, project / "avatar_transcripts",
        {"avatar_transcription_model": "whisper-1"}, transcriber=counted,
    )
    second = transcribe_avatar_chunks(
        discovery.chunks, project / "avatar_transcripts",
        {"avatar_transcription_model": "whisper-1"}, transcriber=counted,
    )
    assert first.transcribed == 2
    assert second.reused == 2

    # Simulate a newly configured model capability for cache-key testing only.
    import avatar_timing
    monkeypatch.setattr(avatar_timing, "SUPPORTED_TIMESTAMP_MODELS", {"whisper-1", "test-compatible-model"})
    third = transcribe_avatar_chunks(
        discovery.chunks, project / "avatar_transcripts",
        {"avatar_transcription_model": "test-compatible-model"}, transcriber=counted,
    )
    assert third.transcribed == 2
    assert third.reused == 0
    assert len(calls) == 4


def test_unsupported_timestamp_model_fails_clearly(monkeypatch) -> None:
    from avatar_timing import transcription_settings, validate_transcription_capabilities
    monkeypatch.delenv("OPENAI_TRANSCRIPTION_MODEL", raising=False)
    settings = transcription_settings({"avatar_transcription_model": "gpt-4o-mini-transcribe"})
    try:
        validate_transcription_capabilities(settings)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected incompatible transcription model to fail")
    assert "gpt-4o-mini-transcribe" in message
    assert "word-level timestamps" in message
    assert "whisper-1" in message


def test_whisper_workflow_and_additive_model_metadata(tmp_path: Path, monkeypatch) -> None:
    project, avatars = setup_project(tmp_path)
    discovery = discover_avatar_chunks(avatars)
    monkeypatch.delenv("OPENAI_TRANSCRIPTION_MODEL", raising=False)
    config = {"avatar_transcription_model": "whisper-1", "avatar_alignment_threshold": 90}
    transcription = transcribe_avatar_chunks(
        discovery.chunks, project / "avatar_transcripts", config, transcriber=fake_payload
    )
    assert transcription.success
    transcript_payload = json.loads(
        (project / "avatar_transcripts" / "S001_avatar.json").read_text(encoding="utf-8")
    )
    cache_settings = transcript_payload["_avatar_timing"]["transcription_settings"]
    assert cache_settings == {
        "model": "whisper-1",
        "response_format": "verbose_json",
        "timestamp_granularities": ["segment", "word"],
        "language": None,
    }
    result = build_actual_timeline(project, avatars, config)
    assert result.success
    manifest = json.loads((project / "avatar_timing_manifest.json").read_text(encoding="utf-8"))
    assert manifest["transcription_model"] == "whisper-1"
    assert manifest["response_format"] == "verbose_json"
    assert manifest["timestamp_granularities"] == ["segment", "word"]
    report = (project / "avatar_alignment_report.md").read_text(encoding="utf-8")
    assert "Transcription Model: whisper-1" in report
    assert "Word Timing Available: Yes" in report
    with (project / "08_actual_timeline.csv").open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle))[0].keys() == {
            "Scene ID", "Script Text", "Actual Audio Start", "Actual Audio End",
            "Duration", "Avatar Chunk", "Timing Source",
        }


def _write_many_scene_project(tmp_path: Path, chunk_count: int, scene_count: int = 147):
    project = tmp_path / f"project_{chunk_count}_{scene_count}"
    avatars = project / "avatars"
    avatars.mkdir(parents=True)
    tokens = [f"word{i}" for i in range(1, scene_count + 1)]
    with (project / "07_production_sheet.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scene_id", "script_excerpt"])
        writer.writeheader()
        for index, token in enumerate(tokens, 1):
            writer.writerow({"scene_id": f"S{index:03d}", "script_excerpt": token})
    (project / "06a_voice_script.md").write_text(" ".join(tokens) + "\n", encoding="utf-8")
    groups = [tokens[i::chunk_count] for i in range(chunk_count)]
    # Use contiguous slices rather than round-robin so global transcript order matches narration.
    base, remainder = divmod(scene_count, chunk_count)
    cursor = 0
    chunk_texts = []
    for index in range(chunk_count):
        size = base + (1 if index < remainder else 0)
        chunk_texts.append(tokens[cursor:cursor + size])
        cursor += size
        (avatars / f"c{index + 1}.mp4").write_bytes(f"chunk-{index + 1}".encode())
    return project, avatars, chunk_texts


def _chunk_transcriber(text_by_stem):
    def transcriber(path: Path, _config: dict) -> dict:
        words = text_by_stem[path.stem]
        return {
            "text": " ".join(words),
            "duration": float(len(words)),
            "segments": [{"start": 0.0, "end": float(len(words)), "text": " ".join(words)}],
            "words": [
                {"word": word, "start": float(index), "end": float(index + 1)}
                for index, word in enumerate(words)
            ],
        }
    return transcriber


def test_c1_through_c3_auto_detected(tmp_path: Path) -> None:
    from avatar_timing import chunk_sequence_info
    project, avatars, _ = _write_many_scene_project(tmp_path, 3)
    discovery = discover_avatar_chunks(avatars)
    info = chunk_sequence_info(discovery)
    assert [chunk.path.name for chunk in discovery.chunks] == ["c1.mp4", "c2.mp4", "c3.mp4"]
    assert info.detected_count == info.expected_count == 3
    assert info.missing_numbers == []


def test_c1_through_c6_auto_detected(tmp_path: Path) -> None:
    from avatar_timing import chunk_sequence_info
    _, avatars, _ = _write_many_scene_project(tmp_path, 6)
    info = chunk_sequence_info(discover_avatar_chunks(avatars))
    assert info.detected_count == 6
    assert info.last_chunk == "c6.mp4"


def test_c1_through_c18_auto_detected_without_limit(tmp_path: Path) -> None:
    from avatar_timing import chunk_sequence_info
    _, avatars, _ = _write_many_scene_project(tmp_path, 18)
    info = chunk_sequence_info(discover_avatar_chunks(avatars))
    assert info.detected_count == info.expected_count == 18
    assert info.last_chunk == "c18.mp4"


def test_numeric_chunk_sort_places_c10_after_c9(tmp_path: Path) -> None:
    _, avatars, _ = _write_many_scene_project(tmp_path, 12)
    names = [chunk.path.name for chunk in discover_avatar_chunks(avatars).chunks]
    assert names[8:11] == ["c9.mp4", "c10.mp4", "c11.mp4"]


def test_missing_c3_detected_from_folder_sequence(tmp_path: Path) -> None:
    from avatar_timing import chunk_sequence_info
    _, avatars, _ = _write_many_scene_project(tmp_path, 5)
    (avatars / "c3.mp4").unlink()
    info = chunk_sequence_info(discover_avatar_chunks(avatars))
    assert info.detected_count == 4
    assert info.expected_count == 5
    assert info.missing_numbers == [3]


def test_six_chunks_map_to_147_scenes(tmp_path: Path) -> None:
    project, avatars, chunk_texts = _write_many_scene_project(tmp_path, 6, 147)
    discovery = discover_avatar_chunks(avatars)
    text_by_stem = {f"c{index + 1}": words for index, words in enumerate(chunk_texts)}
    summary = transcribe_avatar_chunks(
        discovery.chunks, project / "avatar_transcripts", {}, transcriber=_chunk_transcriber(text_by_stem)
    )
    assert summary.success and summary.transcribed == 6
    result = build_actual_timeline(project, avatars, {"avatar_alignment_threshold": 90})
    assert result.success
    assert result.rows == 147
    with (project / "08_actual_timeline.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 147


def test_cumulative_global_word_and_segment_offsets(tmp_path: Path) -> None:
    import avatar_timing
    project, avatars, _ = _write_many_scene_project(tmp_path, 2, 4)
    discovery = discover_avatar_chunks(avatars)
    payloads = {
        "c1": ["word1", "word2"],
        "c2": ["word3", "word4"],
    }
    transcribe_avatar_chunks(
        discovery.chunks, project / "avatar_transcripts", {}, transcriber=_chunk_transcriber(payloads)
    )
    loaded, failures = avatar_timing._load_transcript_payloads(discovery.chunks, project / "avatar_transcripts", {})
    assert not failures
    assert loaded[1]["offset"] == 2.0
    assert loaded[1]["words"][0]["start"] == 2.0
    assert loaded[1]["segments"][0]["start"] == 2.0
    assert loaded[1]["segments"][0]["end"] == 4.0


def test_scene_timing_can_cross_chunk_boundary(tmp_path: Path) -> None:
    project = tmp_path / "cross_boundary"
    avatars = project / "avatars"
    avatars.mkdir(parents=True)
    with (project / "07_production_sheet.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scene_id", "script_excerpt"])
        writer.writeheader()
        writer.writerow({"scene_id": "S001", "script_excerpt": "alpha beta gamma delta"})
    (project / "06a_voice_script.md").write_text("alpha beta gamma delta\n", encoding="utf-8")
    (avatars / "c1.mp4").write_bytes(b"one")
    (avatars / "c2.mp4").write_bytes(b"two")
    discovery = discover_avatar_chunks(avatars)
    transcribe_avatar_chunks(
        discovery.chunks,
        project / "avatar_transcripts",
        {},
        transcriber=_chunk_transcriber({"c1": ["alpha", "beta"], "c2": ["gamma", "delta"]}),
    )
    result = build_actual_timeline(project, avatars, {})
    assert result.success
    with (project / "08_actual_timeline.csv").open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["Avatar Chunk"] == "c1.mp4 to c2.mp4"
    assert row["Actual Audio Start"] == "00:00:00.000"
    assert row["Actual Audio End"] == "00:00:04.000"


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg is required")
def test_large_mp4_extracts_audio_without_modifying_source(tmp_path: Path) -> None:
    source = tmp_path / "c1.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=160x90:r=25:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-c:a", "aac", str(source),
    ], check=True)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    output_dir = tmp_path / "avatar_transcripts"
    prepared = prepare_transcription_media(source, output_dir, {
        "avatar_transcription_upload_threshold_mib": 0.01,
        "avatar_transcription_audio_bitrate_kbps": 32,
        "avatar_transcription_keep_temp_audio": True,
    })
    assert prepared.extracted
    assert prepared.upload_path.name == "c1_transcription_audio.mp3"
    assert prepared.upload_size < int(0.01 * 1024 * 1024)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert abs(prepared.source_duration - prepared.extracted_duration) <= 0.25


def test_missing_ffmpeg_has_installation_guidance(tmp_path: Path, monkeypatch) -> None:
    import avatar_timing
    source = tmp_path / "c1.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(avatar_timing, "ffmpeg_available", lambda: False)
    with pytest.raises(RuntimeError, match="Install FFmpeg"):
        prepare_transcription_media(source, tmp_path / "out", {})


def test_duration_mismatch_blocks_transcription(tmp_path: Path, monkeypatch) -> None:
    import avatar_timing
    source = tmp_path / "c1.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "out" / "_temp_audio" / "c1_transcription_audio.mp3"
    monkeypatch.setattr(avatar_timing, "ffmpeg_available", lambda: True)
    durations = iter([10.0, 8.0])
    monkeypatch.setattr(avatar_timing, "media_duration", lambda _path: next(durations))
    def fake_run(*_args, **_kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"audio")
        return subprocess.CompletedProcess([], 0, "", "")
    monkeypatch.setattr(avatar_timing.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="duration mismatch"):
        prepare_transcription_media(source, tmp_path / "out", {})


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg is required")
def test_small_audio_can_be_uploaded_directly(tmp_path: Path) -> None:
    audio = tmp_path / "c1.wav"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(audio)
    ], check=True)
    prepared = prepare_transcription_media(audio, tmp_path / "out", {"avatar_transcription_upload_threshold_mib": 5})
    assert not prepared.extracted
    assert prepared.upload_path == audio


def test_completed_chunks_are_reused_after_later_failure(tmp_path: Path) -> None:
    project, avatars = setup_project(tmp_path)
    discovery = discover_avatar_chunks(avatars)
    calls = []
    def flaky(path: Path, config: dict) -> dict:
        calls.append(path.name)
        if path.name.startswith("S002") and calls.count(path.name) == 1:
            raise RuntimeError("temporary outage")
        return fake_payload(path, config)
    with pytest.raises(AvatarTranscriptionError):
        transcribe_avatar_chunks(discovery.chunks, project / "avatar_transcripts", {}, transcriber=flaky)
    result = transcribe_avatar_chunks(discovery.chunks, project / "avatar_transcripts", {}, transcriber=flaky)
    assert result.reused == 1
    assert result.transcribed == 1
    assert calls.count("S001_avatar.mp4") == 1


def test_production_page_persists_and_logs_transcription_errors() -> None:
    source = Path(__file__).parents[1].joinpath("app.py").read_text(encoding="utf-8")
    assert "st.session_state[error_key]" in source
    assert 'st.expander("Technical Error Details")' in source
    assert 'avatar_transcription_error.log' in source
    assert 'logging.exception("Avatar transcription failed")' in source
    assert 'st.session_state.pop(error_key, None)' in source


def test_load_transcript_payloads_accepts_current_cache_with_extraction_settings(tmp_path: Path) -> None:
    import avatar_timing

    project, avatars, _ = _write_many_scene_project(tmp_path, 1, 1)
    discovery = discover_avatar_chunks(avatars)
    transcript_dir = project / "avatar_transcripts"
    summary = transcribe_avatar_chunks(
        discovery.chunks,
        transcript_dir,
        {},
        transcriber=_chunk_transcriber({"c1": ["word1"]}),
    )

    assert summary.success
    assert avatar_timing.transcript_cache_is_current(discovery.chunks[0], transcript_dir, {})
    loaded, failures = avatar_timing._load_transcript_payloads(discovery.chunks, transcript_dir, {})
    assert not failures
    assert len(loaded) == 1


def test_scene_alignment_does_not_drift_when_scene_text_has_unapproved_words(tmp_path: Path) -> None:
    scene_count = 120
    project = tmp_path / "no_cursor_drift"
    avatars = project / "avatars"
    avatars.mkdir(parents=True)
    approved_words = [f"marker{index}" for index in range(1, scene_count + 1)]
    with (project / "07_production_sheet.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scene_id", "script_excerpt"])
        writer.writeheader()
        for index, marker in enumerate(approved_words, 1):
            # This production-only direction is absent from the approved voice script.
            # A greedy cursor that assumes scene token length accumulates drift.
            writer.writerow({
                "scene_id": f"S{index:03d}",
                "script_excerpt": f"{marker} hold",
            })
    (project / "06a_voice_script.md").write_text(" ".join(approved_words) + "\n", encoding="utf-8")
    (avatars / "c1.mp4").write_bytes(b"one")
    discovery = discover_avatar_chunks(avatars)
    transcribe_avatar_chunks(
        discovery.chunks,
        project / "avatar_transcripts",
        {},
        transcriber=_chunk_transcriber({"c1": approved_words}),
    )

    result = build_actual_timeline(project, avatars, {"avatar_alignment_threshold": 90})

    assert result.success
    assert result.rows == scene_count
    with (project / "08_actual_timeline.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[50]["Scene ID"] == "S051"
    assert rows[50]["Actual Audio Start"] == "00:00:50.000"
    assert rows[-1]["Scene ID"] == "S120"
    assert rows[-1]["Actual Audio Start"] == "00:01:59.000"
    assert rows[-1]["Actual Audio End"] == "00:02:00.000"


def test_s155_same_word_boundary_is_resolved_to_positive_word_timing(tmp_path: Path, monkeypatch) -> None:
    """Regression for the live S155 zero-duration boundary collapse."""
    import avatar_timing

    project = tmp_path / "s155_boundary_collision"
    avatars = project / "avatars"
    avatars.mkdir(parents=True)
    scenes = [
        ("S154", "before boundary"),
        ("S155", "be used with meals in a way that supports your overall eating pattern. Those are"),
        ("S156", "following boundary"),
    ]
    with (project / "07_production_sheet.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scene_id", "script_excerpt"])
        writer.writeheader()
        for scene_id, text in scenes:
            writer.writerow({"scene_id": scene_id, "script_excerpt": text})
    (project / "06a_voice_script.md").write_text("alpha bridge omega\n", encoding="utf-8")
    (avatars / "c1.mp4").write_bytes(b"one")

    discovery = discover_avatar_chunks(avatars)
    transcribe_avatar_chunks(
        discovery.chunks,
        project / "avatar_transcripts",
        {},
        transcriber=_chunk_transcriber({"c1": ["alpha", "bridge", "omega"]}),
    )

    # The middle approved token has no direct mapping. The old independent
    # forward/backward lookup produced start=word 2 and end=word 0, then clamped
    # both timestamps to the same value. Global range resolution assigns S155
    # the adjacent real word timing instead.
    monkeypatch.setattr(avatar_timing, "_alignment_map", lambda *_args: ({0: 0, 2: 2}, 100.0))
    monkeypatch.setattr(
        avatar_timing,
        "_scene_approved_spans",
        lambda loaded_scenes, _tokens: [
            (loaded_scenes[0], 0, 0),
            (loaded_scenes[1], 1, 1),
            (loaded_scenes[2], 2, 2),
        ],
    )

    result = build_actual_timeline(project, avatars, {"avatar_alignment_threshold": 90})

    assert result.success
    with (project / "08_actual_timeline.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    s155 = next(row for row in rows if row["Scene ID"] == "S155")
    assert s155["Script Text"] == scenes[1][1]
    assert s155["Actual Audio Start"] == "00:00:01.000"
    assert s155["Actual Audio End"] == "00:00:02.000"
    assert float(s155["Duration"]) > 0
    assert all(float(row["Duration"]) > 0 for row in rows)


def test_timeline_is_not_written_when_a_word_has_non_positive_timing(tmp_path: Path) -> None:
    project = tmp_path / "invalid_word_duration"
    avatars = project / "avatars"
    avatars.mkdir(parents=True)
    with (project / "07_production_sheet.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scene_id", "script_excerpt"])
        writer.writeheader()
        writer.writerow({"scene_id": "S155", "script_excerpt": "spoken"})
    (project / "06a_voice_script.md").write_text("spoken\n", encoding="utf-8")
    (avatars / "c1.mp4").write_bytes(b"one")
    discovery = discover_avatar_chunks(avatars)

    def zero_word_payload(_path: Path, _config: dict) -> dict:
        return {
            "text": "spoken",
            "duration": 1.0,
            "segments": [{"start": 0.0, "end": 1.0, "text": "spoken"}],
            "words": [{"word": "spoken", "start": 0.5, "end": 0.5}],
        }

    transcribe_avatar_chunks(
        discovery.chunks, project / "avatar_transcripts", {}, transcriber=zero_word_payload
    )
    with pytest.raises(RuntimeError, match=r"Scene S155 has invalid timeline timing:.*duration=0\.000.*spoken"):
        build_actual_timeline(project, avatars, {})
    assert not (project / "08_actual_timeline.csv").exists()

@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.0, "00:00:00.000"),
        (59.999, "00:00:59.999"),
        (60.0, "00:01:00.000"),
        (61.25, "00:01:01.250"),
        (599.999, "00:09:59.999"),
        (599.9996, "00:10:00.000"),
        (600.0, "00:10:00.000"),
        (3599.9996, "01:00:00.000"),
        (3600.0, "01:00:00.000"),
        (3660.5, "01:01:00.500"),
    ],
)
def test_seconds_to_timestamp_normalizes_clock_carries(seconds: float, expected: str) -> None:
    from avatar_timing import _seconds_to_timestamp

    assert _seconds_to_timestamp(seconds) == expected


def test_seconds_to_timestamp_never_serializes_second_60() -> None:
    import re
    from avatar_timing import _seconds_to_timestamp

    samples = [
        second + fraction
        for second in range(0, 7_201)
        for fraction in (0.0, 0.0004, 0.0006, 0.4999, 0.9994, 0.9996)
    ]
    invalid_seconds = re.compile(r"^\\d{2,}:\\d{2}:([6-9]\\d)(?:\\.|,)")
    invalid_minutes = re.compile(r"^\\d{2,}:([6-9]\\d):")
    for value in samples:
        formatted = _seconds_to_timestamp(value)
        assert invalid_seconds.search(formatted) is None
        assert invalid_minutes.search(formatted) is None


def test_timestamp_round_trip_within_millisecond_tolerance() -> None:
    from avatar_timing import _seconds_to_timestamp
    from timeline_builder import parse_timeline_time

    samples = [0.0, 59.999, 60.0, 61.25, 599.999, 599.9996, 600.0, 3599.9996, 3600.0, 7325.4326]
    for value in samples:
        parsed = parse_timeline_time(_seconds_to_timestamp(value))
        assert abs(parsed - value) <= 0.0005 + 1e-12


def test_s081_timestamp_fixture_normalizes_without_changing_duration() -> None:
    from avatar_timing import _seconds_to_timestamp
    from timeline_builder import parse_timeline_time

    start_seconds = 599.9996
    duration_seconds = 10.120
    end_seconds = start_seconds + duration_seconds

    start_text = _seconds_to_timestamp(start_seconds)
    end_text = _seconds_to_timestamp(end_seconds)

    assert start_text == "00:10:00.000"
    assert end_text == "00:10:10.120"
    assert f"{duration_seconds:.3f}" == "10.120"
    # Millisecond serialization can shift both endpoints equally while the
    # numeric duration source remains untouched.
    assert parse_timeline_time(end_text) - parse_timeline_time(start_text) == pytest.approx(duration_seconds, abs=0.001)
