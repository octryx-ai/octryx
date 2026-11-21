"""Cancelling a paused run: the paused node and every node after it are recorded as cancelled."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Approval, FlowNodeRun
from ....models.agent.orchestrator_agent import ORCHESTRATOR_STATUS_CANCELLED, OrchestratorAgentRun
from ....models.runtime.flow_definition import FlowDefinitionVersion
from ....time_utils import utc_now
from ...approval import resolve_approval_request
from .graph import _normalize_edge, topological_sort_nodes
from .model import NODE_STATUS_CANCELLED, NODE_STATUS_PAUSED
from .node_runs import _flow_node_runs
from .run_state import _audit_flow_event, _set_runtime_failure, _sync_runtime_acceptance


async def cancel_v2_flow_dag(
    db: AsyncSession,
    *,
    run_id: str,
    user_id: str,
    reason: str | None = None,
) -> OrchestratorAgentRun:
    orchestrator_run = await db.get(OrchestratorAgentRun, run_id)
    if orchestrator_run is None or not orchestrator_run.flow_definition_version_id:
        raise ValueError("Flow run not found")
    version = await db.get(FlowDefinitionVersion, orchestrator_run.flow_definition_version_id)
    if version is None:
        raise ValueError("Flow definition version not found")
    node_runs = await _flow_node_runs(db, run_id=orchestrator_run.id)
    paused_node_run = next(
        (node_run for node_run in reversed(node_runs) if node_run.status == NODE_STATUS_PAUSED),
        None,
    )
    if paused_node_run is None:
        raise ValueError("Flow run has no paused node")
    approval_id = str((paused_node_run.output_json or {}).get("approval_id") or "").strip()
    if approval_id:
        approval = await db.get(Approval, approval_id)
        if approval is not None and approval.status == "pending":
            await resolve_approval_request(
                db,
                approval_id=approval.id,
                resolved_by=user_id,
                status="rejected",
                reason=reason or "Cancelled from Flow Builder trace",
            )
    await _stop_paused_flow(
        db,
        orchestrator_run=orchestrator_run,
        version=version,
        paused_node_run=paused_node_run,
        user_id=user_id,
        action="flow.cancelled",
        reason=reason or "Flow run was cancelled.",
    )
    return orchestrator_run


async def _stop_paused_flow(
    db: AsyncSession,
    *,
    orchestrator_run: OrchestratorAgentRun,
    version: FlowDefinitionVersion,
    paused_node_run: FlowNodeRun,
    user_id: str,
    action: str,
    reason: str,
) -> None:
    paused_node_run.status = NODE_STATUS_CANCELLED
    paused_node_run.output_json = {
        **dict(paused_node_run.output_json or {}),
        "approved": False,
        "cancelled": True,
        "reason": reason,
    }
    paused_node_run.completed_at = utc_now()
    paused_node_run.trace_refs_json = {
        **dict(paused_node_run.trace_refs_json or {}),
        "status_transition": ["paused", "cancelled"],
        "reason": reason,
    }
    orchestrator_run.status = ORCHESTRATOR_STATUS_CANCELLED
    orchestrator_run.last_error = reason
    orchestrator_run.completed_at = utc_now()
    _set_runtime_failure(
        orchestrator_run,
        reason,
        source="approval",
        node_id=paused_node_run.node_id,
        node_type=paused_node_run.node_type,
        required_action="human_review",
    )
    await _persist_cancelled_downstream_nodes(
        db,
        orchestrator_run=orchestrator_run,
        version=version,
        paused_node_id=paused_node_run.node_id,
        reason=reason,
    )
    await _audit_flow_event(
        db,
        user_id=user_id,
        session_id=orchestrator_run.session_id,
        action=action,
        run=orchestrator_run,
        node_id=paused_node_run.node_id,
        details={"reason": reason},
    )
    await _sync_runtime_acceptance(
        db,
        user_id=user_id,
        session_id=orchestrator_run.session_id,
        run=orchestrator_run,
        node_id=paused_node_run.node_id,
        reason=reason,
    )
    await db.flush()


async def _persist_cancelled_downstream_nodes(
    db: AsyncSession,
    *,
    orchestrator_run: OrchestratorAgentRun,
    version: FlowDefinitionVersion,
    paused_node_id: str,
    reason: str,
) -> None:
    definition = dict(version.definition_json or {})
    nodes = [dict(node) for node in definition.get("nodes") or [] if isinstance(node, dict)]
    edges = [_normalize_edge(edge) for edge in definition.get("edges") or [] if isinstance(edge, dict)]
    ordered_node_ids = topological_sort_nodes(nodes, edges)
    if paused_node_id not in ordered_node_ids:
        return
    existing = {node_run.node_id for node_run in await _flow_node_runs(db, run_id=orchestrator_run.id)}
    node_map = {str(node.get("id") or ""): node for node in nodes}
    for node_id in ordered_node_ids[ordered_node_ids.index(paused_node_id) + 1 :]:
        if node_id in existing:
            continue
        node = node_map[node_id]
        db.add(
            FlowNodeRun(
                orchestrator_run_id=orchestrator_run.id,
                flow_definition_version_id=version.id,
                node_id=node_id,
                node_type=str(node.get("type") or ""),
                status=NODE_STATUS_CANCELLED,
                output_json={"reason": reason},
                trace_refs_json={
                    "node_label": node.get("label"),
                    "node_type": node.get("type"),
                    "status_transition": ["pending", "cancelled"],
                    "reason": reason,
                },
                completed_at=utc_now(),
            )
        )
    await db.flush()

