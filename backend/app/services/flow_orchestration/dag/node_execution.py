"""Running one node by type: tool, agent, router, join, output, approval and the refused types."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models.agent.orchestrator_agent import OrchestratorAgentRun
from ...approval import ensure_approval_request
from ...flow_runtime_governance import FlowRuntimeLimits, FlowRuntimeUsage
from ...runtime_failure_errors import FlowInputContractError
from ..conditional_rules import ensure_router_rules_valid
from ..flow_agent_step import execute_flow_agent_step
from ..run_capability import flow_tool_context_capability
from .conditions import _condition_matches
from .evidence import _flow_final
from .model import FlowPausedError
from .run_state import _audit_flow_event
from .tool_node import _execute_tool_node


async def _execute_node(
    db: AsyncSession,
    *,
    orchestrator_run: OrchestratorAgentRun,
    node: dict[str, Any],
    input_snapshot: dict[str, Any],
    initial_input: dict[str, Any],
    project_id: str | None,
    project_config: dict[str, Any],
    user_id: str,
    agent_type: str,
    limits: FlowRuntimeLimits,
    usage: FlowRuntimeUsage,
) -> dict[str, Any]:
    node_type = str(node.get("type") or "").strip()
    node_id = str(node.get("id") or "").strip()
    config = dict(node.get("config") or {})

    if node_type in {"trigger", "input_schema", "input"}:
        return dict(initial_input)
    if node_type in {"tool_step", "retrieval"}:
        return await _execute_tool_node(
            db=db,
            node_id=node_id,
            config=config,
            input_snapshot=input_snapshot,
            initial_input=initial_input,
            project_id=project_id,
            project_config=project_config,
            user_id=user_id,
            session_id=orchestrator_run.session_id,
            limits=limits,
            usage=usage,
            run_capability=await flow_tool_context_capability(db, orchestrator_run),
        )
    if node_type in {"agent_step", "supervisor"}:
        # Real agent execution or an explicit failure; never a fabricated result.
        return await execute_flow_agent_step(
            db,
            orchestrator_run=orchestrator_run,
            node_id=node_id,
            node_type=node_type,
            config=config,
            input_snapshot=input_snapshot,
            user_id=user_id,
            agent_type=agent_type,
            limits=limits,
            usage=usage,
        )
    return await _execute_control_node(
        db, orchestrator_run=orchestrator_run, node=node, node_type=node_type, config=config,
        input_snapshot=input_snapshot, user_id=user_id,
    )


async def _execute_control_node(
    db: AsyncSession,
    *,
    orchestrator_run: OrchestratorAgentRun,
    node: dict[str, Any],
    node_type: str,
    config: dict[str, Any],
    input_snapshot: dict[str, Any],
    user_id: str,
) -> dict[str, Any]:
    if node_type == "router":
        return _execute_router_node(config, input_snapshot)
    if node_type == "parallel":
        return {"parallel": True, "input": input_snapshot}
    if node_type == "join":
        return _execute_join_node(config, input_snapshot)
    if node_type == "output":
        return {"result": _flow_final(input_snapshot)}
    if node_type == "approval":
        pause_output = await _create_approval_pause(
            db,
            orchestrator_run=orchestrator_run,
            node=node,
            input_snapshot=input_snapshot,
            user_id=user_id,
        )
        raise FlowPausedError(str(pause_output["reason"]), pause_output)
    if node_type in {"evaluation", "subflow"}:
        # Never a fabricated pass or pass-through: a DAG has no evidence to judge and runs no child workflow.
        replacement = "a gate" if node_type == "evaluation" else "a sub_workflow node"
        raise FlowInputContractError(
            f"A '{node_type}' node does not run in a flow graph; use {replacement} in a workflow that runs in phases."
        )
    if node_type in {"human_task", "learning_proposal"}:
        raise FlowPausedError(f"{node_type} requires human review before downstream execution.")
    return {"result": input_snapshot}


async def _create_approval_pause(
    db: AsyncSession,
    *,
    orchestrator_run: OrchestratorAgentRun,
    node: dict[str, Any],
    input_snapshot: dict[str, Any],
    user_id: str,
) -> dict[str, Any]:
    config = dict(node.get("config") or {})
    node_id = str(node.get("id") or "")
    title = str(config.get("title") or node.get("label") or "Flow approval required").strip()
    prompt = str(config.get("prompt") or config.get("approval_policy") or "Approve this flow step to continue.").strip()
    approval = await ensure_approval_request(
        db,
        requested_by=user_id,
        action=f"Flow approval: {title}",
        reason=(
            f"{prompt}\n\n"
            f"flow_run_id={orchestrator_run.id}\n"
            f"flow_version_id={orchestrator_run.flow_definition_version_id}\n"
            f"node_id={node_id}"
        ),
        session_id=orchestrator_run.session_id,
    )
    await _audit_flow_event(
        db,
        user_id=user_id,
        session_id=orchestrator_run.session_id,
        action="flow.approval_paused",
        run=orchestrator_run,
        node_id=node_id,
        details={
            "approval_id": approval.id,
            "prompt": prompt,
            "approval_mode": config.get("approval_mode") or "approve_reject",
            "required_role": config.get("required_role"),
            "input_keys": sorted(str(key) for key in input_snapshot.keys())[:30],
        },
    )
    return {
        "reason": "Approval node paused the flow.",
        "approval_id": approval.id,
        "approval": {
            "id": approval.id,
            "action": approval.action,
            "status": approval.status,
            "title": title,
            "prompt": prompt,
            "approval_mode": config.get("approval_mode") or "approve_reject",
            "required_role": config.get("required_role"),
        },
    }


def _execute_router_node(config: dict[str, Any], input_snapshot: dict[str, Any]) -> dict[str, Any]:
    ensure_router_rules_valid(config)  # A malformed rule fails here instead of falling to the default
    routes = config.get("routes") if isinstance(config.get("routes"), list) else []
    for route in routes:
        if not isinstance(route, dict):
            continue
        when = route.get("when")
        if _condition_matches(when if isinstance(when, dict) else {}, input_snapshot):
            return {"route": str(route.get("route") or route.get("target") or "default"), "input": input_snapshot}
    default_route = str(config.get("default_route") or "default")
    return {"route": default_route, "input": input_snapshot}


def _execute_join_node(config: dict[str, Any], input_snapshot: dict[str, Any]) -> dict[str, Any]:
    strategy = str(config.get("strategy") or "collect").strip().lower()
    if strategy == "merge":
        merged: dict[str, Any] = {}
        for value in input_snapshot.values():
            if isinstance(value, dict):
                merged.update(value)
        return merged
    return {"joined": input_snapshot}
