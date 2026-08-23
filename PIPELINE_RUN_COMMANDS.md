# Pipeline Run Commands

## Title Agent V2

For project: `Projects/<topic_slug>/`

Run `Title_Agent` using the authoritative contract in `Agents/Title_Agent.md` and the synchronized title engine contract in `System/SYS_04_TITLE_ENGINE.json`.

Title generation must create:

- `03_titles.md`
- `03_titles.csv`

Use this exact `03_titles.csv` header for all NEW Title Agent generation:

```csv
rank,title,title_family,packaging_style,hook_used,anchor_variation,target_audience,consensus_fit,medical_safety,audience_fit,viewer_benefit,viewer_curiosity_raw,viewer_curiosity_weighted,search_intent_type,search_intent_score,thumbnail_compatibility,novelty,clarity,overall_score,packaging_confidence,risk_level,risk_note,experimental,finalist,recommendation_type,recommended_thumbnail_direction,thumbnail_must_not_repeat,primary_viewer_problem,primary_research_mechanism,thumbnail_emotion,publish_recommendation
```

Do not migrate existing older project CSV files automatically. New generation must use the V2 schema.
