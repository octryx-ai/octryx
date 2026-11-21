"""Contract tests: the selected workflow is the only execution contract."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.core.context.run_context_routing import resolve_turn_routing_profile
from app.services.run_capability import decide_run_capability
from app.services.run_capability.escalation import capability_escalation_request
from app.services.security_analyzer import analyze_security_risk
from app.services.workflow_contracts.decisions import (
    ALLOW_CHANGES,
    CAPABILITY_ESCALATION_DECISION,
    WorkflowDecisionError,
    validate_workflow_decisions,
)
from app.services.workflow_routing.explicit_selection import explicit_mode_no_selection_resolution
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from app.services.workflow_runs.binding import phase_resolution
from app.services.workflow_runs.phase_validation import validate_phase_payload
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from app.tools.runtime_impl._runtime_command_policy import _policy_block_result

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


def _phase_resolution(workflow_key: str, node_id: str) -> dict:
    """The resolution a workflow run's phase turn carries: the phase's inline contract."""
    node = next(node for key, node in _phases() if key == workflow_key and node["id"] == node_id)
    run = SimpleNamespace(id=f"run-{workflow_key}", workflow_key=workflow_key, workflow_kind="phased", node_state={})
    return phase_resolution(run=run, node_id=node_id, definition=node["config"])


async def _routing(db, *, resolution: dict, agent_type: str, decisions: dict | None = None):
    metadata = {ROUTING_RESOLUTION_KEY: resolution}
    if decisions:
        metadata["workflow_decisions"] = decisions
    routing = await resolve_turn_routing_profile(
        db=db,
        session_metadata=metadata,
        user_message="Fix the order total rounding.",
        agent_type=agent_type,
        project_id=None,
        agent_definition=None,
        runtime_target_id=None,
    )
    return routing, metadata


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
async def test_a_change_phase_keeps_its_declared_class_inside_a_workflow_run(db):
    routing, metadata = await _routing(db, resolution=_phase_resolution("bug-fix-reproduction", "fix"),
                                       agent_type="diagnosis")
    capability = metadata["execution_profile"]["capability"]
    assert (capability["class"], capability["capped_outside_run"]) == ("change", False)
    assert capability["source"] == "workflow_definition" and capability["enforced"] is True
    # The contradicting request mode is ignored and recorded, never applied.
    assert capability["requested_agent_type"] == "diagnosis"
    assert capability["agent_type_ignored"] is True
    assert routing.run_capability.effective_agent_type == "coding"
    assert metadata["execution_profile"]["status"] == "allowed"
    # The guardrail profile follows the capability, not the diagnosis mode key.
    report = await analyze_security_risk("bash", BRANCH_COMMAND, _context(routing.run_capability.tool_context_state()))
    assert report.action == "allow"


@pytest.mark.asyncio
async def test_a_read_only_turn_refuses_a_write_tool_and_offers_no_escalation(db, tmp_path):
    routing, metadata = await _routing(db, resolution=_phase_resolution("incident-analysis", "evidence"),
                                       agent_type="coding")
    state = routing.run_capability.tool_context_state()
    assert state["class"] == "read_only"
    assert metadata["execution_profile"]["capability"]["agent_type_ignored"] is True

    result = await execute_tool(
        "write_workspace_file",
        {"path": "notes.md", "content": "x"},
        _context(state, workspace_root=str(tmp_path)),
    )
    assert result["capability_refusal"] == {
        "tool_name": "write_workspace_file",
        "run_capability": "read_only",
        "required_capability": "change",
        "escalation": "not_available",
    }
    assert "only inside a workflow run" in result["error"]
    assert result["tool_execution"]["policy"] == "run_capability"
    assert not (tmp_path / "notes.md").exists()

    # A guarded shell command is refused by capability, not parked as an approval.
    command_refusal = await _policy_block_result("bash", BRANCH_COMMAND, _context(state))
    assert command_refusal["capability_refusal"]["escalation"] == "not_available"
    assert "approval_required" not in command_refusal
    # A read-only refusal offers no "allow changes in this session" question.
    assert capability_escalation_request([{"result": result}]) is None


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


@pytest.mark.asyncio
async def test_chat_without_workflow_is_read_only(db):
    routing, metadata = await _routing(db, resolution=explicit_mode_no_selection_resolution(), agent_type="coding")

    capability = metadata["execution_profile"]["capability"]
    assert (capability["class"], capability["source"], capability["enforced"]) == ("read_only", "chat_default", True)
    assert routing.run_capability.effective_agent_type == "diagnosis"
    assert metadata["execution_profile"]["effective_agent_type"] == "diagnosis"
    # The explicit coding mode no longer promotes the routing intent.
    assert routing.strategy_decision.routing_intent != "coding"
