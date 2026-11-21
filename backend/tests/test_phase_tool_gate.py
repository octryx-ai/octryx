"""A phase turn of a workflow run gets its tool surface from the PHASE.

The phase reuses the family id ``knowledge_request`` for its contract message; a tool plan that resolved a
family definition with that id would select only ``knowledge_search``/``knowledge_read`` (max 4 calls): execution
control would hide every other Clarify tool, a forced-call planner would force the knowledge search, and a family
artifact contract would declare the turn complete.

These tests walk the server turn path stage by stage with the real functions — phase resolution (``phase_definition``
+ ``phase_resolution``), turn tool surface, run-context tool definitions (capability catalog, agent ``tools_deny``,
visibility, routing tool policy, Workspace policy), session catalog, tool plan, execution control (visible filter
and call-time enforcement), forced calls and the artifact contract — for every phase of A–E.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.agent.core.context.context_planner import plan_turn_context
from app.agent.core.context.run_context_tool_policy import INSTRUCTION_META_TOOL, tool_routing_resolution_for_turn
from app.agent.core.context.run_context_tooling import build_run_context_tool_definitions
from app.agent.core.context.turn_tool_surface import resolve_turn_tool_surface
from app.agent.engine.messages._engine_message_helpers import (
    _exclude_tool_definitions as exclude_tool_definitions,
)
from app.agent.engine.messages._engine_message_helpers import (
    _filter_tool_definitions as filter_tool_definitions,
)
from app.models import WorkflowRun
from app.services.governed_default_tool_sets import TOOL_SET_BY_CAPABILITY_CLASS
from app.services.tool_catalog.resolution import resolve_session_tool_catalog
from app.services.tool_planning import build_tool_execution_control_contract, build_trace_only_tool_plan_contract
from app.services.tool_planning.phase_plan import PHASE_INTENT
from app.services.tool_planning.runtime_enforcement import (
    enforce_tool_execution_control,
    filter_tool_definitions_for_execution_control,
)
from app.services.workflow_contracts.artifact_contract import workflow_artifact_contract_satisfied
from app.services.workflow_contracts.registry import plan_next_workflow_tool_calls, workflow_phase_tool_names
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from app.services.workflow_runs.binding import phase_resolution
from app.services.workflow_runs.graph import parse_phased_definition
from app.services.workflow_runs.phase_contract import phase_definition
from app.services.workflow_runs.states import KIND_PHASED
from app.tools.context import ToolContext
from app.tools.registry import get_all_tools_with_plugins
from app.tools.visibility import filter_tool_definitions_by_visibility
from tests.phased_seed_definitions import seed_definitions

# The family toolset a Clarify turn must not be narrowed to.
FAMILY_KNOWLEDGE_PLAN = {"knowledge_search", "knowledge_read"}


def _phases() -> list[tuple[str, str]]:
    return [
        (seed["key"], node["id"])
        for seed in seed_definitions()
        for node in seed["definition"]["nodes"]
        if node.get("type") == "phase"
    ]


def _resolution(seed_key: str, node_id: str, *, mutate=None) -> dict[str, Any]:
    seed = next(item for item in seed_definitions() if item["key"] == seed_key)
    definition = copy.deepcopy(seed["definition"])
    if mutate is not None:
        mutate(next(node for node in definition["nodes"] if node["id"] == node_id))
    node = parse_phased_definition(definition).nodes[node_id]
    run = WorkflowRun(id="run-ptg", workflow_key=seed_key, workflow_kind=KIND_PHASED, current_node_id=node_id,
                      context={}, node_state={"iteration": 1, "entry": 1})
    return phase_resolution(run=run, node_id=node_id, definition=phase_definition(run, node))


def _allowlist(resolution: dict[str, Any]) -> set[str]:
    return set(resolution["tool_policy"]["allowlist"]) - set(resolution["tool_policy"].get("denylist") or [])


def _names(definitions: list[dict[str, Any]]) -> set[str]:
    return {str((item.get("function") or {}).get("name") or "") for item in definitions} - {""}


async def _server_turn(resolution: dict[str, Any], *, agent_deny: tuple[str, ...] = (),
                       history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The server turn path from the routing resolution to the tools the model is offered and may call."""
    contract = resolution["workflow_contract"]
    capability_type = TOOL_SET_BY_CAPABILITY_CLASS[contract["capability_class"]]
    agent_definition = {"name": "Engineer", "toolSurface": "governed", "toolsDeny": list(agent_deny), "steps": []}
    # prepare: the session's routing resolution governs the tools, whatever the strategy picked.
    tool_resolution = tool_routing_resolution_for_turn({ROUTING_RESOLUTION_KEY: resolution})
    plan = resolve_turn_tool_surface(
        plan_turn_context(project_id="p1", agent_definition=None, session_metadata={}, history_count=0),
        capability_type=capability_type, workflow_id=resolution["workflow_id"], workflow_contract=contract,
        routing_resolution=tool_resolution, agent_definition=agent_definition, project_config={},
        capability_class=contract["capability_class"])
    tool_context = ToolContext(user_id="u1", project_ids=[], roles=["admin"], session_id="s1",
                               project_config={}, db=None, workspace_root="/tmp/workspace")
    definitions = await build_run_context_tool_definitions(
        db=None, tool_context=tool_context, capability_type=capability_type, include_tools=plan.include_tools,
        tool_allowlist=plan.tool_allowlist or [], blocked_tools=plan.blocked_tools,
        agent_definition=agent_definition, get_all_tools_with_plugins=get_all_tools_with_plugins,
        filter_tool_definitions=filter_tool_definitions, exclude_tool_definitions=exclude_tool_definitions,
        workflow_routing_policy_resolution=tool_resolution,
    ) if plan.include_tools else []
    # tool planning + execution control, as ``prepare_runtime_messages`` runs them every iteration.
    request_analysis = {"workflow_routing_policy_resolution": resolution, "workflow_contract": contract}
    catalog_resolution = resolve_session_tool_catalog(
        tool_definitions=definitions, capability_type=capability_type, request_analysis=request_analysis,
        workflow_contract=contract, tool_context=tool_context)
    tool_plan = build_trace_only_tool_plan_contract(
        current_turn_content="Work on this phase.", request_analysis=request_analysis, workflow_contract=contract,
        session_tool_catalog=catalog_resolution["catalog"], workflow_process_completed=False)
    control = build_tool_execution_control_contract(
        session_tool_catalog_resolution=catalog_resolution, tool_plan_contract=tool_plan)
    offered, _runtime = filter_tool_definitions_for_execution_control(
        tool_definitions=definitions, execution_control_contract=control)
    offered_names = _names(offered)
    turn_history = list(history or [])
    def call(name: str, *, step_tools: set[str] | None = None) -> dict[str, Any] | None:
        """The call-time gate the executor runs before any cache or dispatch (``turn_tools``)."""
        return enforce_tool_execution_control(
            tool_name=name, context_snapshot={"tool_execution_control_contract": control},
            turn_tool_history=turn_history, current_allowed_tool_names=step_tools or set())

    refused = {name for name in offered_names if call(name)}
    return {
        "call": call,
        # What the capability catalog offers with the Workspace's connectors (visibility), independent of the phase.
        "available": _names(filter_tool_definitions_by_visibility(
            get_all_tools_with_plugins(agent_type=capability_type), tool_context.project_config)),
        "plan": plan,
        "built": _names(definitions), "offered": offered_names, "refused": refused,
        "tool_plan": tool_plan, "control": control,
        "forced": plan_next_workflow_tool_calls(contract, turn_tool_history=turn_history, covered_evidence_axes=set(),
                                                allowed_tool_names=offered_names),
        "complete": workflow_artifact_contract_satisfied(contract, turn_tool_history=turn_history),
    }


def test_every_a_to_e_workflow_has_phases_under_test():
    keys = {key for key, _node in _phases()}
    assert keys >= {"bug-fix-reproduction", "jira-intake-triage", "feature-delivery-tdd", "incident-analysis"}
    assert ("feature-delivery-tdd", "clarify") in _phases()


@pytest.mark.parametrize(("seed_key", "node_id"), _phases())
@pytest.mark.asyncio
async def test_each_phase_turn_is_offered_and_may_call_its_allowlist(seed_key, node_id):
    resolution = _resolution(seed_key, node_id)
    allowlist = _allowlist(resolution)
    turn = await _server_turn(resolution)

    expected = (allowlist | {INSTRUCTION_META_TOOL}) & turn["available"]
    assert turn["plan"].tool_surface_source == "selected_definition"
    assert turn["offered"] == turn["built"] == expected
    # Only tools the capability catalog or connector visibility does not offer are absent: never a family narrowing.
    assert allowlist - turn["offered"] <= allowlist - turn["available"]
    assert turn["refused"] == set()
    assert turn["tool_plan"]["intent_class"] == PHASE_INTENT
    assert turn["tool_plan"]["validation"]["valid"], turn["tool_plan"]["validation"]
    assert {item["tool"] for item in turn["tool_plan"]["selected_tools"]} == expected
    # The whole phase surface is the hard gate; there is no budget gate.
    assert turn["control"]["enforcement"] == {"enabled": True, "selected_tool_gate": True, "budget_gate": False,
                                              "max_tool_calls": 0}
    assert set(turn["control"]["selected_tools"]) == expected
    assert turn["control"]["blockers"] == []
    if "bash" not in allowlist:
        assert turn["call"]("bash")["code"] == "phase_tool_not_offered"
    # No planner forces calls, and no family artifact contract ends the turn: the phase checks do.
    assert turn["forced"] == []
    assert turn["complete"] is False


@pytest.mark.asyncio
async def test_clarify_is_offered_the_code_work_item_and_submit_tools_not_the_family_knowledge_plan():
    turn = await _server_turn(_resolution("feature-delivery-tdd", "clarify"))

    assert {"read_workspace_file", "code_search", "grep_workspace", "work_item_context",
            "submit_test_contract"} <= turn["offered"]
    assert turn["offered"] != FAMILY_KNOWLEDGE_PLAN
    assert turn["tool_plan"]["max_tool_calls"] == 0  # no 4-call family budget


@pytest.mark.asyncio
async def test_many_calls_never_exhaust_a_phase_turn():
    history = [{"tool_name": "read_workspace_file", "status": "success", "result": {"content": "x"}}] * 30
    turn = await _server_turn(_resolution("feature-delivery-tdd", "implement"), history=history)

    assert turn["refused"] == set()
    assert {"write_workspace_file", "edit_workspace_file", "run_test_suite"} <= turn["offered"]
    assert turn["complete"] is False
    clarify = await _server_turn(_resolution("feature-delivery-tdd", "clarify"), history=history[:5])
    assert clarify["refused"] == set()  # more than four calls: never a 4-call family budget


@pytest.mark.asyncio
async def test_the_phase_agents_tools_deny_narrows_the_phase_surface():
    turn = await _server_turn(_resolution("feature-delivery-tdd", "clarify"), agent_deny=("code_search",))

    assert "code_search" not in turn["offered"]
    assert "submit_test_contract" in turn["offered"]


@pytest.mark.asyncio
async def test_a_tool_outside_the_phase_allowlist_is_never_offered():
    resolution = _resolution("feature-delivery-tdd", "clarify")
    turn = await _server_turn(resolution)

    assert not {"write_workspace_file", "run_test_suite", "bash"} & turn["offered"]
    assert turn["offered"] - {INSTRUCTION_META_TOOL} <= _allowlist(resolution)


@pytest.mark.asyncio
async def test_a_call_outside_the_phase_surface_is_refused_even_within_the_capability():
    turn = await _server_turn(_resolution("feature-delivery-tdd", "clarify"))

    # bash is in the read-only capability's catalog, but not in Clarify's allowlist.
    assert "bash" in turn["available"] and "bash" not in turn["offered"]
    for tool in ("bash", "write_workspace_file", "run_test_suite"):
        assert turn["call"](tool)["code"] == "phase_tool_not_offered"
    # An agent's step tools never widen the phase surface.
    assert turn["call"]("bash", step_tools={"bash"})["code"] == "phase_tool_not_offered"
    assert turn["call"]("submit_test_contract") is None


@pytest.mark.asyncio
async def test_a_phase_without_a_tool_policy_fails_closed_never_on_the_family_surface():
    def drop_policy(node):
        node["config"].pop("tool_policy", None)

    turn = await _server_turn(_resolution("feature-delivery-tdd", "clarify", mutate=drop_policy))

    assert turn["plan"].tool_surface_source == "phase_without_tool_policy"
    assert turn["plan"].include_tools is False
    assert turn["offered"] == set()
    # An empty surface denies every injected call: never "no selected tools = unlimited".
    assert turn["control"]["enforcement"]["deny_all_tools"] is True
    for tool in ("bash", "knowledge_search", "submit_test_contract"):
        assert turn["call"](tool)["code"] == "phase_tool_not_offered"


@pytest.mark.parametrize(("seed_key", "node_id"), _phases())
def test_a_retired_workflow_sharing_the_phase_id_never_feeds_planning(seed_key, node_id):
    contract = _resolution(seed_key, node_id)["workflow_contract"]
    family = {key: value for key, value in contract.items() if key != "workflow_run_phase"}

    assert workflow_phase_tool_names(contract) == []
    plan = build_trace_only_tool_plan_contract(
        current_turn_content="", request_analysis={}, workflow_contract=contract,
        session_tool_catalog={"entries": [{"name": "knowledge_search"}, {"name": "knowledge_read"}]})
    assert plan["intent_class"] == PHASE_INTENT
    assert plan["intent_contract"]["fallback_policy"] == "phase_tool_policy"
    # Control: the same id without the phase marker still resolves its code-registry family (a non-run turn).
    if family["workflow_id"] == "knowledge_request":
        assert set(workflow_phase_tool_names(family)) >= FAMILY_KNOWLEDGE_PLAN
