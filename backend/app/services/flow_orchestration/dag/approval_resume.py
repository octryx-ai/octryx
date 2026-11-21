"""Resuming a run paused at an approval: approve and continue, or reject and stop."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Approval, FlowNodeRun
from ....models.agent.orchestrator_agent import (
    ORCHESTRATOR_STATUS_COMPLETED,
    ORCHESTRATOR_STATUS_PAUSED,
    OrchestratorAgentRun,
)
from ....models.runtime.flow_definition import FlowDefinitionVersion
from ....time_utils import utc_now
from ...approval import resolve_approval_request
from ..planning import ensure_flow_run_plan, sync_flow_run_plan_from_node_runs
from .cancellation import _stop_paused_flow
from .context import DagRun, LoopMode
from .evidence import _artifact_refs, _evidence_summary, _flow_final
from .graph import _last_output, parse_flow_graph
from .loop import _run_remaining_nodes
from .model import NODE_STATUS_CANCELLED, NODE_STATUS_COMPLETED, NODE_STATUS_PAUSED, NODE_STATUS_SKIPPED
from .node_runs import _flow_node_runs
from .run_state import _audit_flow_event, _set_run_progress, _sync_runtime_acceptance
from .runtime_setup import _resumed_dag_run
from .stops import _stop_if_too_many_nodes

_APPROVAL_RESUME_MODE = LoopMode(
    detail={"after_resume": True},
    start_phase="running",
    skip_reason="Upstream branch was not selected.",
    error_suffix=" after resume",
    commit_each_node=False,
    commit_on_limit_stop=False,
    catch_node_limits=True,
    check_validation=False,
    count_attempts=False,
    node_count_reason="Paused flow run failed because runtime limits were exceeded.",
    run_limit_reason="Paused flow continuation failed because runtime limits were exceeded.",
    paused_reason="Resumed flow run is waiting for human review.",
    node_limit_reason="Resumed flow node failed because runtime limits were exceeded.",
    node_failed_reason="Resumed flow node failed before acceptance.",
)


async def resume_v2_flow_dag(
    db: AsyncSession,
    *,
    run_id: str,
    decision: str,
    approval_id: str | None,
    human_input: dict[str, Any] | None,
    user_id: str,
    reason: str | None = None,
) -> OrchestratorAgentRun:
    orchestrator_run, version, paused_node_run, approval = await _load_paused_approval(
        db, run_id=run_id, approval_id=approval_id,
    )
    normalized_decision = str(decision or "").strip().lower()
    if normalized_decision not in {"approve", "reject"}:
        raise ValueError("decision must be approve or reject")

    if normalized_decision == "reject":
        await resolve_approval_request(
            db,
            approval_id=approval.id,
            resolved_by=user_id,
            status="rejected",
            reason=reason or "Rejected from Flow Builder trace",
        )
        await _stop_paused_flow(
            db,
            orchestrator_run=orchestrator_run,
            version=version,
            paused_node_run=paused_node_run,
            user_id=user_id,
            action="flow.approval_rejected",
            reason=reason or "Flow approval was rejected.",
        )
        return orchestrator_run

    await _approve_paused_node(
        db, orchestrator_run=orchestrator_run, paused_node_run=paused_node_run, approval=approval,
        human_input=human_input, user_id=user_id, reason=reason,
    )
    return await _continue_after_paused_node(
        db,
        orchestrator_run=orchestrator_run,
        version=version,
        paused_node_run=paused_node_run,
        existing_node_runs=await _flow_node_runs(db, run_id=orchestrator_run.id),
        user_id=user_id,
    )


async def _load_paused_approval(
    db: AsyncSession, *, run_id: str, approval_id: str | None,
) -> tuple[OrchestratorAgentRun, FlowDefinitionVersion, FlowNodeRun, Approval]:
    orchestrator_run = await db.get(OrchestratorAgentRun, run_id)
    if orchestrator_run is None or not orchestrator_run.flow_definition_version_id:
        raise ValueError("Flow run not found")
    if orchestrator_run.status != ORCHESTRATOR_STATUS_PAUSED:
        raise ValueError("Flow run is not paused")
    version = await db.get(FlowDefinitionVersion, orchestrator_run.flow_definition_version_id)
    if version is None:
        raise ValueError("Flow definition version not found")

    node_runs = await _flow_node_runs(db, run_id=orchestrator_run.id)
    paused_node_run = next(
        (node_run for node_run in reversed(node_runs) if node_run.status == NODE_STATUS_PAUSED),
        None,
    )
    if paused_node_run is None:
        raise ValueError("Paused flow run has no paused node")
    approval_id = approval_id or str((paused_node_run.output_json or {}).get("approval_id") or "").strip() or None
    if not approval_id:
        raise ValueError("Paused flow run has no approval request")
    approval = await db.get(Approval, approval_id)
    if approval is None or approval.session_id != orchestrator_run.session_id:
        raise ValueError("Approval request does not belong to this flow run")
    return orchestrator_run, version, paused_node_run, approval


async def _approve_paused_node(
    db: AsyncSession,
    *,
    orchestrator_run: OrchestratorAgentRun,
    paused_node_run: FlowNodeRun,
    approval: Approval,
    human_input: dict[str, Any] | None,
    user_id: str,
    reason: str | None,
) -> None:
    await resolve_approval_request(
        db,
        approval_id=approval.id,
        resolved_by=user_id,
        status="approved",
        reason=reason or "Approved from Flow Builder trace",
    )
    approved_output = {
        "approved": True,
        "approval_id": approval.id,
        "approved_by": user_id,
        "human_input": human_input or {},
        "proposal": paused_node_run.input_json,
    }
    paused_node_run.status = NODE_STATUS_COMPLETED
    paused_node_run.output_json = approved_output
    paused_node_run.evidence_summary_json = _evidence_summary(approved_output)
    paused_node_run.artifact_refs_json = _artifact_refs(approved_output)
    paused_node_run.completed_at = utc_now()
    paused_node_run.trace_refs_json = {
        **dict(paused_node_run.trace_refs_json or {}),
        "status_transition": ["paused", "completed"],
        "approval_id": approval.id,
        "approved_by": user_id,
    }
    await _audit_flow_event(
        db,
        user_id=user_id,
        session_id=orchestrator_run.session_id,
        action="flow.approval_approved",
        run=orchestrator_run,
        node_id=paused_node_run.node_id,
        details={"approval_id": approval.id, "human_input_keys": sorted((human_input or {}).keys())[:30]},
    )
    await db.flush()


async def _continue_after_paused_node(
    db: AsyncSession,
    *,
    orchestrator_run: OrchestratorAgentRun,
    version: FlowDefinitionVersion,
    paused_node_run: FlowNodeRun,
    existing_node_runs: list[FlowNodeRun],
    user_id: str,
) -> OrchestratorAgentRun:
    graph = parse_flow_graph(version)
    ensure_flow_run_plan(orchestrator_run, nodes=graph.nodes, ordered_node_ids=graph.ordered_node_ids)
    sync_flow_run_plan_from_node_runs(orchestrator_run, existing_node_runs)
    paused_index = graph.ordered_node_ids.index(paused_node_run.node_id)
    outputs = {
        node_run.node_id: dict(node_run.output_json or {})
        for node_run in existing_node_runs
        if node_run.status == NODE_STATUS_COMPLETED
    }
    skipped = {
        node_run.node_id
        for node_run in existing_node_runs
        if node_run.status in {NODE_STATUS_SKIPPED, NODE_STATUS_CANCELLED}
    }
    existing_node_ids = {node_run.node_id for node_run in existing_node_runs}
    ctx = await _resumed_dag_run(
        db, orchestrator_run=orchestrator_run, version=version, graph=graph, existing_node_runs=existing_node_runs,
        user_id=user_id, mode=_APPROVAL_RESUME_MODE, outputs=outputs, skipped=skipped,
    )
    ctx.existing_node_ids = existing_node_ids
    if await _stop_if_too_many_nodes(
        db, orchestrator_run, node_count=len(graph.nodes), limits=ctx.limits, user_id=user_id,
        mode=_APPROVAL_RESUME_MODE,
    ):
        return orchestrator_run
    if await _run_remaining_nodes(ctx, paused_index + 1):
        return orchestrator_run
    await _finish_approval_resume(ctx, paused_node_run)
    return orchestrator_run


async def _finish_approval_resume(ctx: DagRun, paused_node_run: FlowNodeRun) -> None:
    db, run, user_id = ctx.db, ctx.run, ctx.user_id
    run.status = ORCHESTRATOR_STATUS_COMPLETED
    run.last_error = None
    run.completed_at = utc_now()
    run.merged_output_json = {
        "final": _flow_final(ctx.final_output or _last_output(ctx.outputs, ctx.graph.ordered_node_ids)),
        "nodes": ctx.outputs,
    }
    await _sync_runtime_acceptance(
        db, user_id=user_id, session_id=run.session_id, run=run, node_id="",
        reason="Paused flow run completed after approval.",
    )
    await _audit_flow_event(
        db, user_id=user_id, session_id=run.session_id, action="flow.resumed_completed", run=run,
        node_id=paused_node_run.node_id, details={"resumed_from_node_id": paused_node_run.node_id},
    )
    await _audit_flow_event(
        db, user_id=user_id, session_id=run.session_id, action="flow.run_completed", run=run, node_id="",
        details={"after_resume": True, "tool_calls": ctx.usage.tool_calls},
    )
    _set_run_progress(run, node_index=len(ctx.graph.ordered_node_ids), node_id="", phase="completed")
    await db.flush()
