# B-roll Collector

`Tools/broll_collector.py` collects clear-license stock B-roll for a finished Senior Health AI production package.

It reads:

- `Projects/<topic_slug>/07_production_sheet.csv`
- `Projects/<topic_slug>/12_broll_prompts.md`

It downloads matched videos into:

- `Projects/<topic_slug>/assets/broll/`

It creates or updates:

- `Projects/<topic_slug>/asset_manifest.csv`

## Setup

Create a local `.env` file at the project root:

```text
PEXELS_API_KEY=your_pexels_key
PIXABAY_API_KEY=your_pixabay_key
```

You may use either API key or both. Pexels is searched first, then Pixabay.

## Run

From the project root:

```powershell
python Tools/broll_collector.py --project Projects/<topic_slug>
```

Dry run without downloads:

```powershell
python Tools/broll_collector.py --project Projects/<topic_slug> --dry-run
```

## Manifest Columns

`asset_manifest.csv` includes:

- `asset_id`
- `scene_id`
- `source`
- `search_query`
- `local_path`
- `original_url`
- `license`
- `creator`
- `duration`
- `resolution`
- `status`
- `notes`

## Selection Rules

The collector prefers:

- horizontal 16:9 video
- seniors and older adults
- kitchens, food, grocery stores, labels
- doctors, clinics, walking, healthy lifestyle
- clear, calm, non-sensational medical-adjacent visuals

The collector avoids:

- copyrighted or unclear-license videos
- shocking medical visuals
- hospital fear visuals
- fake lab reports
- pills as the main object
- gore
- dialysis fear imagery

If a result is weak, the tool does not force it. The scene is marked:

```text
AI_PROMPT_REQUIRED
```

Use the corresponding entry in `12_broll_prompts.md` to generate that visual manually.

## Notes

- The tool uses only standard Python libraries.
- It does not modify scripts, agents, production sheets, or prompts.
- Pexels and Pixabay license labels are stored in the manifest for review.
- Always review downloaded assets before publishing.
