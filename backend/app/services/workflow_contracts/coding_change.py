"""The ``coding_change_tdd`` family: a workspace code change with a bounded TDD-style test loop."""

from __future__ import annotations

from typing import Any

from .agent_definition import ALL_CODING_DELIVERY_TOOLS
from .models import WorkflowDefinition, WorkflowPhase
from .topic import infer_topic

CODING_CHANGE_TDD_WORKFLOW_ID = "coding_change_tdd"

# The bounded TDD loop's tool surface.
TDD_CYCLE_TOOLS = (
    "analyze_workspace_repository",
    "code_search",
    "read_workspace_file",
    "write_workspace_file",
    "edit_workspace_file",
    "multi_edit_workspace_file",
    "apply_patch_workspace",
    "run_test_suite",
    # Approved verification-contract execution — the
    # completion gate for non-test-suite changes (IaC).
    "run_validation_commands",
    # Large tool results arrive as artifact stubs; the
    # model must be able to load their content.
    "load_tool_artifact",
    "bash",
    "run_cli_command",
    "grep_workspace",
    "glob_workspace_files",
    "get_git_diff",
    # Governed Knowledge: cited version changes and where they apply.
    "knowledge_changes",
    "knowledge_code_impact",
    "knowledge_search",
    "knowledge_read",
    # Delivery hand-off per the coding operating model:
    # verified changes leave the workspace as a branch,
    # pull request, and ticket update. All three stay
    # gated by project tool policy, repository operation
    # policy, and approval enforcement at dispatch.
    *ALL_CODING_DELIVERY_TOOLS,
)


def _configured_workflow_id(request_analysis: dict[str, Any] | None) -> str:
    configured = (request_analysis or {}).get("workflow_contract")
    return str(configured.get("workflow_id") or "").strip() if isinstance(configured, dict) else ""


def match_coding_change_tdd(
    user_message: str,
    *,
    request_analysis: dict[str, Any] | None,
    route_reason: str,
    project_id: str | None,
    capability_type: str | None,
) -> bool:
    del user_message, route_reason, project_id, capability_type
    return _configured_workflow_id(request_analysis) == CODING_CHANGE_TDD_WORKFLOW_ID


def build_coding_change_tdd_contract(
    user_message: str,
    *,
    request_analysis: dict[str, Any] | None,
    route_reason: str,
    project_id: str | None,
    capability_type: str | None,
) -> dict[str, Any]:
    del request_analysis, route_reason, capability_type
    return {
        "workflow_id": CODING_CHANGE_TDD_WORKFLOW_ID,
        "workflow_version": 1,
        "intent_type": "code_change",
        "artifact_type": "code",
        "topic": infer_topic(user_message),
        "project_id": project_id or "",
        "source_user_message": str(user_message or "").strip(),
        "evidence_contract": {
            "required_axes": ["repo_context", "tests_green"],
            "mode": "workspace_tdd",
        },
    }


def plan_coding_change_tdd(
    workflow_contract: dict[str, Any],
    *,
    turn_tool_history: list[dict[str, Any]],
    covered_evidence_axes: set[str] | None,
    allowed_tool_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    del workflow_contract, turn_tool_history, covered_evidence_axes, allowed_tool_names
    return []


def coding_change_tdd_definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id=CODING_CHANGE_TDD_WORKFLOW_ID,
        intent_type="code_change",
        description="Implement a workspace code change with a bounded TDD-style test loop.",
        phases=(WorkflowPhase("tdd_cycle", TDD_CYCLE_TOOLS),),
        matcher=match_coding_change_tdd,
        contract_builder=build_coding_change_tdd_contract,
        planner=plan_coding_change_tdd,
    )


__all__ = [
    "CODING_CHANGE_TDD_WORKFLOW_ID",
    "TDD_CYCLE_TOOLS",
    "build_coding_change_tdd_contract",
    "coding_change_tdd_definition",
    "match_coding_change_tdd",
    "plan_coding_change_tdd",
]
