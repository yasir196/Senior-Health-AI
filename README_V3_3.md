# Senior Health AI V3.3 — Avatar Timing Sync

V3.3 is an additive Production-stage upgrade. It does not add a sidebar page, agent, prompt, or workflow stage and does not change Direct Codex Run.

## Workflow

Production Lock READY → Avatar Timing Sync → OpenAI transcription → approved-script alignment → `08_actual_timeline.csv`.

## Input

Choose an avatar folder containing generic chunks (`c1.mp4`, `c2.mp4`) or scene-based chunks (`S001_avatar.mp4`, `S005_avatar.mp4`). When both schemes are present, scene-based files are selected and generic alternatives are reported. Supported media: MP4, MOV, M4V, WEBM, MP3, M4A, and WAV. Avatar files are never modified.

## Transcription model, timestamps, and cache

The OpenAI adapter requests `verbose_json`, segment timestamps, word timestamps, and writes SRT. The default remains `whisper-1` because the required `timestamp_granularities` behavior and `verbose_json` output are supported by Whisper, while `gpt-4o-mini-transcribe` currently supports JSON-only responses and therefore cannot supply the existing word/segment timestamp contract. Cost does not override timing compatibility.

Model precedence is deterministic:

1. `OPENAI_TRANSCRIPTION_MODEL` environment variable
2. `config.json` → `avatar_transcription_model`
3. Safe default `whisper-1`

Unsupported models fail before transcription with the configured model, missing capabilities, and recommended compatible model. There is no silent fallback.

Each transcript cache record stores the media size, nanosecond modified time, SHA-256 hash, effective model, response format, timestamp granularities, and optional configured language. A media or transcription-setting change forces re-transcription; old JSON/SRT files cannot unlock timeline generation.

The attached V3.2 archive did not contain a reusable OpenAI transcription helper or script. V3.3 therefore isolates the official OpenAI API call in `openai_transcribe_avatar()` while all discovery, cache, alignment, manifest, report, and timeline behavior remains provider-independent and testable.

## Approved wording

`06a_voice_script.md` is the only approved narration wording and is never overwritten. Transcript text is timing evidence only. Existing script, QA, and cleaner reports are read-only.

## Outputs

- `avatar_transcripts/*.json` — full verbose response including word timing when returned
- `avatar_transcripts/*.srt` — subtitle timing for every chunk
- `08_actual_timeline.csv` — scene ID, approved script text, actual start/end, duration, chunk, timing source
- `avatar_timing_manifest.json` — fingerprints, durations, transcript state, alignment, and matched scene range
- `avatar_alignment_report.md` — found/expected/missing/duplicate chunks, transcript success, alignment, and warnings

## Configuration

- `avatar_timing_sync_enabled`: enables the Production-page section
- `avatar_transcription_model`: defaults to `whisper-1`; override with `OPENAI_TRANSCRIPTION_MODEL`
- `avatar_transcription_language`: optional ISO-639-1 language hint; included in the cache key when set
- `avatar_transcription_upload_threshold_mib`: safe upload ceiling; defaults to `24` MiB for the 25 MiB `whisper-1` request limit
- `avatar_transcription_audio_bitrate_kbps`: extracted mono MP3 speech bitrate; defaults to `48` kbps
- `avatar_transcription_duration_tolerance_seconds`: maximum source/extracted duration difference; defaults to `0.25` seconds
- `avatar_transcription_keep_temp_audio`: retain `_temp_audio` files after success for debugging; defaults to `false`
- `avatar_alignment_threshold`: defaults to `92.0`
- `openai_api_key_env`: defaults to `OPENAI_API_KEY`

## Safety and compatibility

The feature is disabled until Production Lock is READY. It does not modify `06_final_script.md`, `06a_voice_script.md`, QA reports, cleaner reports, or avatar media. No CapCut export is implemented in V3.3.

## Model compatibility note

`whisper-1` is the selected default because Avatar Timing Sync requires verbose JSON plus both segment and word timestamps. `gpt-4o-mini-transcribe` can be cheaper for general transcription, but it is intentionally rejected by this workflow while its API response format is JSON-only and does not provide the required timestamp-granularity contract. Live API compatibility was not tested in this release because no valid API credential and media file were supplied.

## Automatic avatar chunk discovery update

Avatar Timing Sync now derives its expected chunk sequence exclusively from the selected avatar folder. Generic HeyGen chunks are detected as a numeric `c1` through `cN` sequence, sorted numerically, with gaps reported from the detected range. Production-scene count is displayed separately and never determines the expected avatar-chunk count.

All detected chunk transcripts are concatenated in numeric order. Local word and segment timestamps receive cumulative global offsets before the approved `06a_voice_script.md` narration is aligned. A single chunk may cover many production scenes, and a scene may cross a chunk boundary. No minimum, maximum, or scenes-per-chunk limit is configured.

