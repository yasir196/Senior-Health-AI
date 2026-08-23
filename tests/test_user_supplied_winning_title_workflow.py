from pathlib import Path
import json
import v31_core

ROOT=Path(__file__).resolve().parents[1]

def test_titles_stage_removed():
    assert "Titles" not in v31_core.WORKFLOW_STAGES
    assert all(stage != "Titles" for stage,_ in v31_core.PIPELINE)

def test_title_agent_removed_from_registry_and_dag():
    reg=json.loads((ROOT/"System/SYS_12_AGENTS.json").read_text(encoding="utf-8"))
    assert "title_agent" not in [a["name"] for a in reg["agents"]]
    dag=json.loads((ROOT/"System/SYS_11_PIPELINE_DAG.json").read_text(encoding="utf-8"))
    assert all(n.get("agent") != "title_agent" for n in dag["nodes"])

def test_downstream_uses_project_json_title():
    for rel in ["Agents/Thumbnail_Agent.md","Agents/Script_Agent.md","Agents/SEO_Agent.md"]:
        text=(ROOT/rel).read_text(encoding="utf-8")
        assert "project.json" in text
        assert "03_titles.md" not in text

def test_thumbnail_ready_without_generated_title_files(tmp_path):
    (tmp_path/"project.json").write_text(json.dumps({"topic":"My Exact Title","anchor_title":"My Exact Title"}),encoding="utf-8")
    for name in ("01_topic_validation.md","02_research_sheet.md","13_fact_check_log.md"):
        (tmp_path/name).write_text("Status: PASS",encoding="utf-8")
    ready,reasons=v31_core.stage_ready(tmp_path,"Thumbnail",{})
    assert ready, reasons
