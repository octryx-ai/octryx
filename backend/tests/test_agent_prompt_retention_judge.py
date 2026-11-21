"""Selected agent instructions must survive supported runtime prompt variants."""

from types import SimpleNamespace

import pytest

from app.agent.core.context.context_planner import plan_turn_context
from app.agent.core.prompts.prompt_builder import build_system_prompt_parts
from app.services.agent_definition_payload import build_agent_execution_prompt


@pytest.mark.parametrize(
    "capability, variant_routing",
    [("diagnosis", {}), ("admin", {}), ("diagnosis", {"full": "minimal"}), ("diagnosis", {"full": "summary"})],
)
def test_explicit_agent_goal_notes_and_output_survive_prompt_composition(capability, variant_routing):
    agent = {
        "name": "Synthetic format judge",
        "goal": "Preserve the synthetic marker CEDAR-GOAL-1140.",
        "description": "",
        "systemPrompt": "Synthetic operating constraint CEDAR-NOTES-1140.",
        "outputPrompt": "Return the supplied result using CEDAR-OUTPUT-1140.",
        "toolSurface": "none",
        "steps": [],
    }
    agent["prompt"] = build_agent_execution_prompt(agent)
    plan = plan_turn_context(
        capability_type=capability,
        project_id=None,
        agent_definition=agent,
        session_metadata={},
        history_count=0,
    )
    assert plan.include_agent_blueprint, "The planner explicitly requires this agent's instructions"
    mode = SimpleNamespace(key=capability, name=capability, capability_type=capability, prompt_instructions="")

    parts = build_system_prompt_parts(
        agent_type=capability,
        agent_mode=mode,
        personality="Explain context. Show relevant logs, metrics and events.",
        memory="",
        skills="",
        agent_definition=agent,
        thinking_level="light",
        prompt_variant=plan.system_prompt_variant,
        prompt_variant_routing=variant_routing,
    )

    for marker in ("CEDAR-GOAL-1140", "CEDAR-NOTES-1140", "CEDAR-OUTPUT-1140"):
        assert parts.combined.count(marker) == 1, f"Configured agent instruction lost or duplicated: {marker}"
    assert parts.stable and "Communication Preferences" in parts.combined
