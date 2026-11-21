"""Workflow-run phase resolutions and loop and strategy contract builders for the loop contract parity tests."""

from __future__ import annotations

import copy
from types import SimpleNamespace

from app.agent.loops.control._loop_workflow_contract_state import WORKFLOW_CONTRACT_METADATA_KEY
from app.agent.loops.setup._loop_setup import initialize_standard_loop_state
from app.services.execution_strategy_service import resolve_execution_strategy
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

PROJECT_ID = "project-w16"


# Fields the loop adds after the selected contract, from run-time state the strategy path does not
# read. Listed so the parity check below is exact on everything else:
# - ``knowledge_lookup_settings``: the project's knowledge-lookup configuration
#   (``apply_knowledge_lookup_config_to_contract`` reads ``project_config``; always set, ``{}`` here).
# The other loop stages (research policy, secure-work verification contract, recorded workflow
# decisions, a resumed persisted contract) read session state that is empty in these turns and
# add nothing; a field they add later is session state, not the selected definition's contract.
# - ``workflow_decisions``: the session's recorded closed decisions, carried on the loop's contract
#   (``apply_workflow_decisions_to_contract``); both builders already read them (W13a), so the
#   decided fields themselves are equal.
LOOP_STAGE_FIELDS = frozenset({"knowledge_lookup_settings", "workflow_decisions"})


def _resolution(workflow_id: str, workflow_class: str, *, key: str = "", tool_policy=None, safety_constraints=None, **configured) -> dict:
    """The routing resolution of a workflow-run phase whose inline contract runs ``workflow_id``."""
    configured = {"workflow_id": workflow_id, "workflow_class": workflow_class, **configured}
    return {
        "source": "db",
        "status": "matched",
        "selection_source": "workflow_run",
        "workflow_key": key or f"{workflow_id}-definition",
        "workflow_id": workflow_id,
        "workflow_class": workflow_class,
        "policy_id": f"policy-{key or workflow_id}",
        "policy_version_id": f"version-{key or workflow_id}",
        "matched_group_id": None,
        "workflow_contract": configured,
        "tool_policy": dict(tool_policy or {}),
        "safety_constraints": dict(safety_constraints or {}),
    }


def _strategy_contract(prompt: str, resolution: dict, agent_type: str = "chat", *, decisions: dict | None = None) -> dict:
    return resolve_execution_strategy(
        prompt=prompt,
        requested_agent_type=agent_type,
        agent_type_explicit=agent_type != "chat",
        project_id=PROJECT_ID,
        workflow_routing_policy_resolution=copy.deepcopy(resolution),
        workflow_decisions=decisions,
    ).workflow_contract


def _loop_turn(prompt: str, resolution: dict, capability_type: str = "diagnosis", **session_metadata) -> tuple[dict, dict]:
    """The standard loop's real setup; returns (loop contract, persisted contract)."""
    session = SimpleNamespace(metadata_={})
    prepared = SimpleNamespace(
        tool_context=SimpleNamespace(project_config={"project_id": PROJECT_ID}, project_ids=[PROJECT_ID]),
        # A context-plan route reason the knowledge guard must judge the same on every path.
        context_plan=SimpleNamespace(route_reason="operations_lookup", domains=[], enforce_domain_coverage=False),
        session_metadata={ROUTING_RESOLUTION_KEY: copy.deepcopy(resolution), **session_metadata},
        tool_definitions=[],
        current_session=session,
    )
    state = initialize_standard_loop_state(
        prepared=prepared,
        capability_type=capability_type,
        current_turn_content=prompt,
        agent_definition=None,
        max_iterations=None,
        thinking_level=None,
        map_reasoning_effort=lambda _level: None,
    )
    return state["request_analysis"].get("workflow_contract") or {}, session.metadata_.get(WORKFLOW_CONTRACT_METADATA_KEY) or {}


def _without_loop_stage(contract: dict) -> dict:
    return {key: value for key, value in contract.items() if key not in LOOP_STAGE_FIELDS}
