"""Contract tests: the selected workflow is the only execution contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.run_capability import decide_run_capability
from app.services.workflow_contracts.decisions import (
    ALLOW_CHANGES,
    CAPABILITY_ESCALATION_DECISION,
    WorkflowDecisionError,
    validate_workflow_decisions,
)
from app.services.workflow_routing.explicit_selection import explicit_mode_no_selection_resolution
from app.services.workflow_runs.phase_validation import validate_phase_payload
from app.tools.context import ToolContext
from app.tools.registry import execute_tool

SEEDS_PATH = Path(__file__).resolve().parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json"
# A branch step of a coding phase, which diagnosis mode once refused.
BRANCH_COMMAND = "git switch fix/order-total 2>/dev/null || git switch -c fix/order-total"


def _phases() -> list[tuple[str, dict]]:
    return [
        (seed["key"], node)
        for seed in json.loads(SEEDS_PATH.read_text())
        for node in seed["definition"]["nodes"]
        if node.get("type") == "phase"
    ]






def _context(state: dict, *, agent_mode_key: str = "diagnosis", workspace_root: str | None = None) -> ToolContext:
    return ToolContext(
        user_id="",
        project_ids=[],
        roles=["developer"],
        session_id="capability-session",
        project_config={"security_analyzer_chain": ["exec_policy", "secret_access"]},
        capability_type="diagnosis",
        agent_mode_key=agent_mode_key,
        run_capability=state,
        workspace_root=workspace_root,
    )






@pytest.mark.asyncio
async def test_a_recorded_allow_changes_raises_nothing_any_more(db, tmp_path):
    assert validate_workflow_decisions({CAPABILITY_ESCALATION_DECISION: ALLOW_CHANGES}) == {
        CAPABILITY_ESCALATION_DECISION: ALLOW_CHANGES
    }
    with pytest.raises(WorkflowDecisionError):
        validate_workflow_decisions({CAPABILITY_ESCALATION_DECISION: "deliver"})

    recorded = decide_run_capability(
        routing_resolution=explicit_mode_no_selection_resolution(),
        requested_agent_type="diagnosis",
        requested_mode_capability="diagnosis",
        recorded_decisions={CAPABILITY_ESCALATION_DECISION: ALLOW_CHANGES},
    )
    assert (recorded.capability_class, recorded.escalated) == ("read_only", False)
    written = await execute_tool(
        "write_workspace_file",
        {"path": "notes.md", "content": "x"},
        _context(recorded.tool_context_state(), agent_mode_key="coding", workspace_root=str(tmp_path)),
    )
    assert written["capability_refusal"]["escalation"] == "not_available"
    assert not (tmp_path / "notes.md").exists()


def test_validator_refuses_read_only_phase_with_write_tools():
    payload = {
        "workflow_id": "knowledge_request",
        "workflow_class": "knowledge_request",
        "workflow_contract": {"workflow_id": "knowledge_request", "capability_class": "read_only", "when_to_use": "x"},
        "tool_policy": {"allowlist": ["knowledge_search", "write_workspace_file"]},
        "safety_constraints": {"diagnosis_mode": True},
    }
    report = validate_phase_payload(payload)
    assert report["valid"] is False
    exceeded = [error for error in report["errors"] if error["code"] == "capability_class_exceeded"]
    assert exceeded and "write_workspace_file" in exceeded[0]["message"]

    missing = validate_phase_payload(
        {**payload, "workflow_contract": {"workflow_id": "knowledge_request", "when_to_use": "x"}}
    )
    assert "missing_capability_class" in {error["code"] for error in missing["errors"]}

    for workflow_key, node in _phases():
        assert node["config"]["workflow_contract"]["capability_class"] in {"read_only", "change"}, workflow_key


