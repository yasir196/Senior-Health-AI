# Image Generation Agent — Implementation Report

## Before-coding inspection

1. **Authoritative final Production prompt source:** `Projects/<project>/10_image_prompts.md`, field `Final AI IMAGE PROMPT`. Slot existence/order originates in `07_production_sheet.csv`; Production creates the final prompt file from those assignments.
2. **Authoritative image destination used by CapCut:** `Projects/<project>/assets/images/image_NNN.png`. `timeline_builder.py` maps AI_IMAGE assignment order to this path; `capcut_export.py` resolves that reference against the selected project root.
3. **Project selection:** `app.py::project_selector()` enumerates `Projects/` and returns `PROJECTS_DIR / selected_name`. Image Generation resolves that path fresh on every rerun/action.
4. **Existing API/config convention:** API keys come from environment variables (`OPENAI_API_KEY` already follows this pattern); JSON configuration comes from root `config.json`.
5. **Existing Runware integration:** none was present in the supplied codebase.
6. **Current filename mapping:** assignment order is `image_001.png`, `image_002.png`, ... and is preserved unchanged.

## Implementation

- Added `image_generation.py` as a downstream-only generation layer.
- Modified `app.py` only to import the new layer and replace the old manual `Genspark Images` page with `Image Generation` UI.
- Added `RUNWARE_API_KEY` placeholder to `.env.example`.
- Added `tests/test_image_generation_agent.py`.
- No Production prompt generation, Production scene allocation, Avatar Timing, Actual Timeline, CapCut exporter, CapCut keyframe, timing, B-roll, or overlay logic was changed.

## UI location

Sidebar: **Image Generation**, immediately after **Production** and before **Files**.

The page includes required/generated/remaining counts, model dropdown, enhancement toggle, original/enhanced prompt preview, Generate Missing Images, Regenerate Selected, Retry Failed, Regenerate Stale Images, Regenerate All With Current Model, per-image status table, and Download Images ZIP.

## Model registry

`MODEL_PROFILES` is configuration-shaped and can be extended through `config.json` key `image_generation_models` without changing generation code. Profiles carry display name, provider, model ID, enhancer, dimensions, text capability, defaults/provider parameters, recommendation flag, and optional cost metadata.

Built-ins:

- P-Image-Ideogram (default/recommended): `prunaai:p-image@ideogram`
- FLUX.1 Schnell: `runware:100@1`

Generation dimensions are 1280×720 (exact 16:9) for both built-ins.

## Prompt enhancement / immutability

`original_prompt` is read from Production and never written back. The P-Image-Ideogram enhancer appends complexity-aware generation clarification while retaining the original prompt verbatim as the prefix. Hand/object scenes get stronger physical-contact/anatomy clarification; blank notebook/screen/no-text scenes explicitly prohibit pseudo-text; explicit readable-text scenes preserve only requested text. A deterministic safety guard falls back to the original prompt if forbidden stronger medical/authority/outcome wording appears.

Enhancement OFF sends the exact original Production prompt.

## Runware API/config

Credential: `RUNWARE_API_KEY` environment variable only; it is never stored in the manifest or logs.

Transport: Runware REST endpoint with bearer authentication and `imageInference` task payload, unique UUID, selected model, positive prompt, width/height, PNG output, sync delivery, and cost response request. The implementation downloads `imageURL`, then validates the actual file before SUCCESS.

## Retry / concurrency

Defaults are configuration-driven:

- `image_generation_retry_count`: 2 if absent
- `image_generation_concurrency`: 3 if absent

Concurrency is bounded to 1–8 workers. Transient timeout/network/429/5xx-style failures are retried with a short bounded backoff. Invalid request/safety-style permanent failures stop retrying for that image and generation continues for the remaining batch.

## Stale behavior

`image_generation_manifest.json` stores the original prompt hash. If Production changes a prompt while the same image filename exists, reconciliation marks that image `STALE`; the file is not deleted or overwritten automatically. The UI exposes **Regenerate Stale Images**.

## Manifest

Per-image records include image number, filename, scene ID, prompt ID, original/enhanced prompt hashes, selected model, provider, model ID, dimensions, output path, status, attempts, timestamp, output SHA-256, safe error summary, elapsed time, and provider-reported cost when available. API keys are never persisted. The manifest is tracking-only and does not control Production assignment or timing.

## Project isolation

Every action resolves the selected project and rebuilds `Projects/<selected>/assets/images/<filename>` from that project. Manifest, prompt source, preview, status, generated assets, and ZIP are all project-local. No previous-project path is cached by the generation module.

## Tests

Added regression coverage for prompt immutability, exact built-in model IDs, model-specific enhancement behavior, canonical filenames, project-specific asset paths, project switching, missing-only behavior, selected-only regeneration, retry, enhancement OFF/ON behavior, safety preservation, manifest hashes, stale detection, valid 16:9 validation, invalid output rejection, exact ZIP names, and secret non-persistence.

Full supplied suite result after implementation: **288 passed**.
