"""The workflow step scaffold keeps a user agent definition's own steps."""

from __future__ import annotations

from app.agent.loops.setup._loop_workflow_scaffold import build_workflow_step_scaffold


def test_scaffold_keeps_user_agent_definition_precedence():
    user_agent = {
        "name": "Custom Ops Agent",
        "steps": [{"name": "Investigate", "isEnabled": True, "allowedTools": ["knowledge_search"]}],
    }
    scaffold = build_workflow_step_scaffold(
        workflow_contract={"workflow_id": "knowledge_request"},
        agent_definition=user_agent,
        capability_type="diagnosis",
    )

    assert scaffold["injected_workflow_agent"] is False
    assert scaffold["agent_definition"] is user_agent
