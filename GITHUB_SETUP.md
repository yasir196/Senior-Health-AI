# GitHub / New PC Setup

This repository is prepared for a private GitHub repository.

## Do not commit secrets
Copy `.env.example` to `.env` on each PC and fill in your own keys locally.
The real `.env` file is ignored by Git.

Expected environment variables:
- `OPENAI_API_KEY`
- `OPENAI_TRANSCRIPTION_MODEL` (default: `whisper-1`)
- `RUNWARE_API_KEY`
- `PEXELS_API_KEY`
- `PIXABAY_API_KEY`

## Base Python setup on Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## External tools used by the workflow
Install these separately if you use the related features:
- FFmpeg / ffprobe — Avatar Timing / media timing workflows
- OpenAI Codex CLI — Direct Codex agent runs

After installation, confirm they are available from the terminal:

```powershell
ffmpeg -version
ffprobe -version
codex --version
```

## Run the app

```powershell
streamlit run app.py
```

## Project data
`Projects/` is intentionally kept empty in GitHub. Generated scripts, transcripts,
media, production sheets, and project assets stay local and are not versioned by default.

## First GitHub push

From this folder:

```powershell
git init
git add .
git status
git commit -m "Initial Senior Health AI"
git branch -M main
git remote add origin https://github.com/yasir196/Senior-Health-AI.git
git push -u origin main
```

Before `git commit`, review `git status` and confirm `.env`, local Codex state,
project media, and logs are not listed.
