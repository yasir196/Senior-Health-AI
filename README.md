# Senior Health AI

Senior Health AI is a local content-production workflow for evidence-first senior health YouTube videos. It organizes the process into stage-specific agents, system contracts, reusable knowledge files, templates, validation gates, and a small local Streamlit dashboard.

## What Is Included

- `Agents/` - stage-specific agent instructions for topic selection, research, titles, scripts, production, SEO, thumbnails, telemetry, and related workflow steps.
- `System/` - machine-readable workflow rules, scoring matrices, validation gates, pipeline order, and content engines.
- `Knowledge/` - channel strategy, SOPs, brand rules, viewer psychology notes, title/thumbnail/hook guidance, and production checklists.
- `Templates/` - reusable writing, voice, and compliance templates.
- `Tools/` - helper tooling such as the B-roll collector.
- `Evidence/` - evidence-library scaffolding and review queues.
- `Projects/` - project workspaces and generated handoff files. Large generated media assets are ignored by Git.
- `app.py` - optional local Streamlit dashboard for browsing projects, editing files, and generating Codex commands.

## Repository Safety

This repository is prepared for GitHub with local credentials and generated artifacts excluded from Git:

- `.env` is ignored.
- `extension_yt/evanto/token.txt` is ignored.
- Python caches, temporary folders, archives, generated videos/audio, workbook exports, and generated project media are ignored.
- Use `.env.example` as the public template for required API keys.

Before pushing publicly, rotate any API keys that were ever stored in local files.

## Setup

Install Python dependencies:

```powershell
pip install -r requirements.txt
```

Create a local environment file from the example:

```powershell
copy .env.example .env
```

Then add your own local API keys to `.env`:

```text
PEXELS_API_KEY=
PIXABAY_API_KEY=
```

## Run The Local Dashboard

```powershell
streamlit run app.py
```

Streamlit will print a local URL, usually:

```text
http://localhost:8501
```

The dashboard is local-only. It does not run Codex automatically; it helps create folders, review/edit local files, preview CSV files, and generate commands to use in Codex Desktop.

## Development Checks

Run the Python tests:

```powershell
pytest
```

If `pytest` is not installed:

```powershell
pip install pytest
```

## GitHub Upload

After reviewing the files to be committed:

```powershell
git init
git add .
git status
git commit -m "Initial GitHub-ready project"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
git push -u origin main
```

Replace `YOUR-USERNAME` and `YOUR-REPOSITORY` with your GitHub account and repository name.

## V3.2
See `README_V3_2.md` for Auto Revision Engine, separate writer outputs, Production Cleaner, Advanced QA Dashboard, Script Quality Metrics, Production Lock 2.0 and automatic stage progression.

## V3.3 Avatar Timing Sync

V3.3 keeps the V3.2 workflow unchanged and extends the existing Production page with Avatar Timing Sync. After Production Lock is READY, select a folder containing `c1.mp4`, `c2.mp4`, or scene-based files such as `S001_avatar.mp4`. Scene-based names are preferred when both naming schemes exist.

The sync uses OpenAI transcription with verbose JSON, segment timestamps, word timestamps, and SRT output. Unchanged media is reused from `avatar_transcripts/` through size, modified-time, and SHA-256 fingerprints. The approved `06a_voice_script.md` is read-only and remains the wording authority; transcripts are used only for actual timing alignment.

Generated outputs:

- `avatar_transcripts/<chunk>.json`
- `avatar_transcripts/<chunk>.srt`
- `08_actual_timeline.csv`
- `avatar_timing_manifest.json`
- `avatar_alignment_report.md`

Set `OPENAI_API_KEY` before transcription. The effective model is resolved from `OPENAI_TRANSCRIPTION_MODEL`, then `avatar_transcription_model`, then the safe `whisper-1` default. Whisper remains the default because this workflow requires `verbose_json`, segment timestamps, and word timestamps; incompatible models fail clearly without silent fallback. Model, response format, timestamp granularities, optional language, and media fingerprint are part of the transcript cache key. Configuration keys include `avatar_transcription_model`, optional `avatar_transcription_language`, `avatar_alignment_threshold`, and `openai_api_key_env`. No CapCut export is included in V3.3.

## Automatic avatar chunk discovery update

Avatar Timing Sync now derives its expected chunk sequence exclusively from the selected avatar folder. Generic HeyGen chunks are detected as a numeric `c1` through `cN` sequence, sorted numerically, with gaps reported from the detected range. Production-scene count is displayed separately and never determines the expected avatar-chunk count.

All detected chunk transcripts are concatenated in numeric order. Local word and segment timestamps receive cumulative global offsets before the approved `06a_voice_script.md` narration is aligned. A single chunk may cover many production scenes, and a scene may cross a chunk boundary. No minimum, maximum, or scenes-per-chunk limit is configured.

