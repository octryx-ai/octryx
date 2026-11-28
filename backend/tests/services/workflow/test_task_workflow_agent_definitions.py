"""Workflow agent definitions built for the registry workflow families."""

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


