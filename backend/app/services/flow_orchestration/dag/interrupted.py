"""Resuming a run that was interrupted mid-way (crash, restart, expired lease) from its recorded node attempts."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import FlowNodeRun
from ....models.agent.orchestrator_agent import (
    ORCHESTRATOR_STATUS_CANCELLED,
    ORCHESTRATOR_STATUS_COMPLETED,
    ORCHESTRATOR_STATUS_PAUSED,
    ORCHESTRATOR_STATUS_RUNNING,
    OrchestratorAgentRun,
)
from ....models.runtime.flow_definition import FlowDefinitionVersion
from ....time_utils import utc_now
from ...error_facts import error_facts
from ..planning import ensure_flow_run_plan, sync_flow_run_plan_from_node_runs, update_flow_plan_step
from ..recovery import list_stale_v2_flow_runs
from .context import DagRun, LoopMode
from .evidence import _flow_final
from .graph import _last_output, parse_flow_graph
from .loop import _run_remaining_nodes
from .model import (
    NODE_STATUS_CANCELLED,
    NODE_STATUS_COMPLETED,
    NODE_STATUS_FAILED,
    NODE_STATUS_RUNNING,
    NODE_STATUS_SKIPPED,
)
from .node_runs import _flow_node_runs
from .run_state import _audit_flow_event, _commit_flow_checkpoint, _set_run_progress, _sync_runtime_acceptance
from .runtime_setup import _resumed_dag_run
from .stops import _stop_if_too_many_nodes

_DEFAULT_REASON = "Interrupted flow run resumed."
_INTERRUPTED_RESUME_MODE = LoopMode(
    detail={"after_interrupted_resume": True},
    start_phase="resuming",
    skip_reason="Upstream branch was not selected.",
    error_suffix=" after interrupted resume",
    commit_each_node=True,
    commit_on_limit_stop=True,
    catch_node_limits=False,
    check_validation=False,
    count_attempts=True,
    node_count_reason=None,
    run_limit_reason=None,
    paused_reason="Interrupted flow run is waiting for human review.",
    node_limit_reason=None,
    node_failed_reason="Interrupted flow node failed before acceptance.",
)


async def resume_interrupted_v2_flow_dag(
    db: AsyncSession,
    *,
    run_id: str,
    user_id: str,
    reason: str | None = None,
) -> OrchestratorAgentRun:
    """Resume an interrupted v2 flow run from persisted node traces.

    Completed nodes are treated as authoritative checkpoints and are not rerun.
    Stale running or failed nodes are recorded as recovered attempts, then the
    first incomplete node and its downstream path continue through the normal
    executor and budget checks.
    """
    orchestrator_run, version = await _load_interrupted_run(db, run_id=run_id)
    graph = parse_flow_graph(version)
    existing_node_runs = await _flow_node_runs(db, run_id=orchestrator_run.id)
    ensure_flow_run_plan(orchestrator_run, nodes=graph.nodes, ordered_node_ids=graph.ordered_node_ids)
    sync_flow_run_plan_from_node_runs(orchestrator_run, existing_node_runs)
    completed_outputs, skipped, stale_attempts = _recorded_attempts(existing_node_runs)
    terminal_node_ids = set(completed_outputs) | skipped
    await _retire_stale_attempts(db, orchestrator_run, stale_attempts, user_id=user_id, reason=reason)
    start_index = next(
        (index for index, node_id in enumerate(graph.ordered_node_ids) if node_id not in terminal_node_ids),
        None,
    )
    if start_index is None:
        await _complete_without_rerun(db, orchestrator_run, completed_outputs, graph.ordered_node_ids, user_id)
        return orchestrator_run
    await _record_resume_started(
        db, orchestrator_run, user_id=user_id, node_id=graph.ordered_node_ids[start_index],
        details={
            "completed_nodes": sorted(completed_outputs),
            "skipped_nodes": sorted(skipped),
            "stale_attempt_count": len(stale_attempts),
            "reason": reason or _DEFAULT_REASON,
        },
    )
    ctx = await _resumed_dag_run(
        db, orchestrator_run=orchestrator_run, version=version, graph=graph, existing_node_runs=existing_node_runs,
        user_id=user_id, mode=_INTERRUPTED_RESUME_MODE, outputs=dict(completed_outputs), skipped=skipped,
    )
    if await _stop_if_too_many_nodes(
        db, orchestrator_run, node_count=len(graph.nodes), limits=ctx.limits, user_id=user_id,
        mode=_INTERRUPTED_RESUME_MODE,
    ):
        return orchestrator_run
    if await _run_remaining_nodes(ctx, start_index):
        return orchestrator_run
    await _finish_interrupted_resume(ctx, start_index)
    return orchestrator_run


def _recorded_attempts(
    existing_node_runs: list[FlowNodeRun],
) -> tuple[dict[str, dict[str, Any]], set[str], list[FlowNodeRun]]:
    """Completed outputs, skipped node ids and stale (running or failed) attempts, as recorded."""
    completed_outputs = {
        node_run.node_id: dict(node_run.output_json or {})
        for node_run in existing_node_runs
        if node_run.status == NODE_STATUS_COMPLETED
    }
    skipped = {node_run.node_id for node_run in existing_node_runs if node_run.status == NODE_STATUS_SKIPPED}
    stale_attempts = [
        node_run
        for node_run in existing_node_runs
        if node_run.status in {NODE_STATUS_RUNNING, NODE_STATUS_FAILED}
    ]
    return completed_outputs, skipped, stale_attempts


async def _load_interrupted_run(
    db: AsyncSession, *, run_id: str,
) -> tuple[OrchestratorAgentRun, FlowDefinitionVersion]:
    orchestrator_run = await db.get(OrchestratorAgentRun, run_id)
    if orchestrator_run is None or not orchestrator_run.flow_definition_version_id:
        raise ValueError("Flow run not found")
    if orchestrator_run.status in {
        ORCHESTRATOR_STATUS_COMPLETED,
        ORCHESTRATOR_STATUS_CANCELLED,
        ORCHESTRATOR_STATUS_PAUSED,
    }:
        raise ValueError(f"Flow run status {orchestrator_run.status!r} cannot be interrupted-resumed")
    version = await db.get(FlowDefinitionVersion, orchestrator_run.flow_definition_version_id)
    if version is None:
        raise ValueError("Flow definition version not found")
    return orchestrator_run, version


async def _retire_stale_attempts(
    db: AsyncSession,
    orchestrator_run: OrchestratorAgentRun,
    stale_attempts: list[FlowNodeRun],
    *,
    user_id: str,
    reason: str | None,
) -> None:
    for stale in stale_attempts:
        previous_status = stale.status
        stale.status = NODE_STATUS_CANCELLED
        stale.error = stale.error or "Interrupted flow run recovered before this attempt completed."
        stale.completed_at = stale.completed_at or utc_now()
        stale.trace_refs_json = {
            **dict(stale.trace_refs_json or {}),
            "status_transition": [previous_status, NODE_STATUS_CANCELLED],
            "recovery_reason": reason or _DEFAULT_REASON,
            "retry_planned": True,
        }
        update_flow_plan_step(
            orchestrator_run,
            node_id=stale.node_id,
            status=NODE_STATUS_CANCELLED,
            node_run_id=stale.id,
            reason=reason or _DEFAULT_REASON,
        )
        await _audit_flow_event(
            db,
            user_id=user_id,
            session_id=orchestrator_run.session_id,
            action="flow.node_recovery_retry",
            run=orchestrator_run,
            node_id=stale.node_id,
            details={"previous_status": previous_status, "reason": reason or _DEFAULT_REASON},
        )


async def _complete_without_rerun(
    db: AsyncSession,
    orchestrator_run: OrchestratorAgentRun,
    completed_outputs: dict[str, dict[str, Any]],
    ordered_node_ids: list[str],
    user_id: str,
) -> None:
    orchestrator_run.status = ORCHESTRATOR_STATUS_COMPLETED
    orchestrator_run.last_error = None
    orchestrator_run.completed_at = utc_now()
    orchestrator_run.merged_output_json = {
        "final": _flow_final(_last_output(completed_outputs, ordered_node_ids)),
        "nodes": completed_outputs,
    }
    await _audit_flow_event(
        db, user_id=user_id, session_id=orchestrator_run.session_id, action="flow.interrupted_resume_completed",
        run=orchestrator_run, node_id="", details={"already_complete": True},
    )
    await _commit_flow_checkpoint(db, orchestrator_run)


async def _record_resume_started(
    db: AsyncSession, orchestrator_run: OrchestratorAgentRun, *, user_id: str, node_id: str, details: dict[str, Any],
) -> None:
    orchestrator_run.status = ORCHESTRATOR_STATUS_RUNNING
    orchestrator_run.last_error = None
    orchestrator_run.completed_at = None
    await _audit_flow_event(
        db, user_id=user_id, session_id=orchestrator_run.session_id, action="flow.interrupted_resume_started",
        run=orchestrator_run, node_id=node_id, details=details,
    )
    await _commit_flow_checkpoint(db, orchestrator_run)


async def _finish_interrupted_resume(ctx: DagRun, start_index: int) -> None:
    db, run, user_id = ctx.db, ctx.run, ctx.user_id
    ordered_node_ids = ctx.graph.ordered_node_ids
    run.status = ORCHESTRATOR_STATUS_COMPLETED
    run.last_error = None
    run.completed_at = utc_now()
    run.merged_output_json = {
        "final": _flow_final(ctx.final_output or _last_output(ctx.outputs, ordered_node_ids)),
        "nodes": ctx.outputs,
    }
    await _sync_runtime_acceptance(
        db, user_id=user_id, session_id=run.session_id, run=run, node_id="",
        reason="Interrupted flow run completed after resume.",
    )
    await _audit_flow_event(
        db, user_id=user_id, session_id=run.session_id, action="flow.interrupted_resume_completed", run=run,
        node_id="", details={"resumed_from_node_id": ordered_node_ids[start_index], "tool_calls": ctx.usage.tool_calls},
    )
    await _audit_flow_event(
        db, user_id=user_id, session_id=run.session_id, action="flow.run_completed", run=run, node_id="",
        details={"after_interrupted_resume": True, "tool_calls": ctx.usage.tool_calls},
    )
    _set_run_progress(run, node_index=len(ordered_node_ids), node_id="", phase="completed")
    await _commit_flow_checkpoint(db, run)


async def recover_stale_v2_flow_runs(
    db: AsyncSession,
    *,
    user_id: str,
    limit: int = 20,
    reason: str | None = None,
) -> dict[str, Any]:
    stale_runs = await list_stale_v2_flow_runs(db, limit=limit)
    recovered: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for run in stale_runs:
        try:
            resumed = await resume_interrupted_v2_flow_dag(
                db,
                run_id=run.id,
                user_id=user_id,
                reason=reason or "Stale Flow run lease expired.",
            )
            recovered.append({"run_id": resumed.id, "status": resumed.status})
        except Exception as exc:
            # Batch recovery must keep inspecting other stale runs when one run cannot be resumed.
            failed.append({"run_id": run.id, **error_facts("flow_stale_run_recovery_failed", exc)})
    return {
        "count": len(stale_runs),
        "recovered_count": len(recovered),
        "failed_count": len(failed),
        "recovered": recovered,
        "failed": failed,
    }

