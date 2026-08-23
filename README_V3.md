# Senior Health AI V3

## Main additions
- Codex CLI direct execution using non-interactive `codex exec`
- Separate Title and Thumbnail stages
- Claude Opus writer handoff package stage
- Narrative QA Agent and `14_narrative_qa.md`
- Explicit Medical Gate 2 and `15_medical_gate_2.md`
- ElevenLabs V3 Speech Optimizer stage
- Production lock until Narrative QA and Medical Gate 2 pass
- Genspark AI-image queue
- Updated project dashboard and file manager

## Start
1. Install Python 3.11+ and Codex CLI.
2. In this folder run: `pip install -r requirements.txt`
3. Log in to Codex CLI: `codex login`
4. Start dashboard: `streamlit run app.py`

## Recommended workflow
1. Topic Validation
2. Research + Medical Gate 1
3. Titles
4. Thumbnail
5. Script Outline
6. Prepare Opus Package
7. Write `06_final_script.md` in Claude Opus and save it in the project folder
8. Narrative QA
9. Apply approved narrative revisions manually
10. Medical Gate 2
11. Speech Optimizer
12. Production Package
13. SEO
14. Final QA + Summary

## Security
The distributable does not contain API keys. Copy `.env.example` to `.env` and add your own keys locally.
