from v31_core import sync_project_prompt_state


def sync(state, project: str, *, reset: bool = False) -> str:
    return sync_project_prompt_state(
        state,
        prompt_key="narrative_qa_prompt",
        context_key="narrative_prompt_project",
        context_value=project,
        default_prompt=f"For Projects/{project}/, run Narrative_QA_Agent.",
        force_reset=reset,
    )


def test_narrative_prompt_regenerates_only_when_project_changes():
    state = {}

    project_a_prompt = sync(state, "project-a")
    assert "Projects/project-a/" in project_a_prompt
    assert "project-b" not in project_a_prompt

    state["narrative_qa_prompt"] += "\nManual Project A note."
    assert sync(state, "project-a").endswith("Manual Project A note.")

    project_b_prompt = sync(state, "project-b")
    assert "Projects/project-b/" in project_b_prompt
    assert "Projects/project-a/" not in project_b_prompt
    assert "Manual Project A note." not in project_b_prompt

    project_a_again = sync(state, "project-a")
    assert "Projects/project-a/" in project_a_again
    assert "Projects/project-b/" not in project_a_again


def test_reset_restores_current_projects_default_prompt():
    state = {}
    default_b = sync(state, "project-b")
    state["narrative_qa_prompt"] = "custom text for project-b"

    restored = sync(state, "project-b", reset=True)

    assert restored == default_b
    assert "Projects/project-b/" in restored
    assert "project-a" not in restored


def test_shared_prompt_state_tracks_project_and_stage_context():
    state = {}
    prompt_key = "workflow_agent_prompt"
    context_key = "workflow_agent_prompt_context"

    first = sync_project_prompt_state(
        state,
        prompt_key=prompt_key,
        context_key=context_key,
        context_value="project-a:Narrative QA",
        default_prompt="Projects/project-a/ Narrative QA",
    )
    assert first == "Projects/project-a/ Narrative QA"

    state[prompt_key] += " edited"
    preserved = sync_project_prompt_state(
        state,
        prompt_key=prompt_key,
        context_key=context_key,
        context_value="project-a:Narrative QA",
        default_prompt="Projects/project-a/ Narrative QA",
    )
    assert preserved.endswith(" edited")

    changed = sync_project_prompt_state(
        state,
        prompt_key=prompt_key,
        context_key=context_key,
        context_value="project-b:Medical Gate 2",
        default_prompt="Projects/project-b/ Medical Gate 2",
    )
    assert changed == "Projects/project-b/ Medical Gate 2"
    assert "project-a" not in changed
