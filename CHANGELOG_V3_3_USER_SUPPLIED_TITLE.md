# V3.3 User-Supplied Winning Title Workflow

- Removed the active Titles/Title_Agent workflow stage.
- The exact title entered at New Project -> Anchor / Outlier Title is stored as `project.json.anchor_title` and is the immutable winning title for the project.
- Topic/Outlier Validation validates that exact title promise; Research and Medical Gate 1 test its claims without generating replacements.
- Thumbnail, Script, Production, SEO, Narrative QA, and Final QA use the same project title as their title authority.
- Removed generated-title dependencies (`03_titles.md`, `03_titles.csv`) from active workflow gates, DAG, agent registry, and downstream required inputs.
- Removed Title_Agent/Title Judge/Title Engine from the active build.
- Added regression tests ensuring Thumbnail can proceed without generated title artifacts once validation/research/Medical Gate 1 exist.
