"""Workflow agent definitions built for the registry workflow families."""

from app.services.workflow_contracts.agent_definition import build_workflow_agent_definition
from app.services.workflow_contracts.registry import build_task_workflow_contract


def test_build_task_workflow_contract_builds_a_selected_coding_change_tdd():
    contract = build_task_workflow_contract(
        "In a small Python codebase, implement a build_project_budget_warning_banner helper and include focused pytest tests.",
        request_analysis={"workflow_contract": {"workflow_id": "coding_change_tdd"}},
        route_reason="implicit_mode:coding_prompt",
        project_id="project-1",
        capability_type="change",
    )

    assert contract["workflow_id"] == "coding_change_tdd"
    assert contract["artifact_type"] == "code"
    assert contract["evidence_contract"]["mode"] == "workspace_tdd"


def test_build_workflow_agent_definition_for_coding_change_tdd():
    contract = build_task_workflow_contract(
        "In a small Python codebase, implement a build_project_budget_warning_banner helper and include focused pytest tests.",
        request_analysis={"workflow_contract": {"workflow_id": "coding_change_tdd"}},
        route_reason="implicit_mode:coding_prompt",
        project_id="project-1",
        capability_type="change",
    )

    agent_definition = build_workflow_agent_definition(contract)

    assert agent_definition is not None
    assert agent_definition["name"] == "Code Change TDD"
    assert agent_definition["agentType"] == "change"
    assert [step["name"] for step in agent_definition["steps"]] == ["Implement And Verify Change"]
    step = agent_definition["steps"][0]
    assert step["stepType"] == "tdd_cycle"
    assert "run_cli_command" not in step["allowedTools"]
    assert step["stepConfig"]["tdd_cycle_phases"] == ["write_tests", "make_green"]
    assert "run_test_suite" in agent_definition["prompt"]
    assert "freshly bootstrapped scaffold" in agent_definition["prompt"]
    assert "create the minimal tests and implementation yourself" in step["instructions"]
