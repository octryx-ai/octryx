"""Required tools on workflow phases."""

from __future__ import annotations

from app.services.workflow_contracts.models import WorkflowPhase

# --- GAP 4: phase completion criteria -------------------------------------


def test_workflow_phase_required_tools_default_keeps_to_dict_stable() -> None:
    phase = WorkflowPhase("evidence", ("search_jira_tickets",))

    assert phase.required_tools == ()
    assert phase.to_dict() == {
        "id": "evidence",
        "preferred_tools": ["search_jira_tickets"],
    }


def test_workflow_phase_to_dict_includes_required_tools_additively() -> None:
    phase = WorkflowPhase(
        "validate",
        ("bash", "run_test_suite"),
        required_tools=("run_test_suite",),
    )

    assert phase.to_dict() == {
        "id": "validate",
        "preferred_tools": ["bash", "run_test_suite"],
        "required_tools": ["run_test_suite"],
    }
