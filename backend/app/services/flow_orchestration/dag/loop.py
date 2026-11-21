"""The node loop shared by a fresh run and both kinds of resume."""

from __future__ import annotations

from typing import Any

from ....models import FlowNodeRun
from ...flow_runtime_governance import FlowRuntimeLimitExceededError, ensure_run_duration_within_limits
from ..planning import update_flow_plan_step
from ..validation_loop import record_validation_outcome
from .context import DagRun
from .graph import (
    _all_incoming_skipped,
    _materialize_node_input,
    _selected_router_targets,
    _unselected_router_targets,
)
from .model import FlowPausedError
from .node_execution import _execute_node
from .node_runs import _complete_node_run, _next_node_attempt, _persist_skipped_node, _start_node_run
from .run_state import _commit_flow_checkpoint, _set_run_progress
from .stops import _fail_node, _fail_node_on_limit, _pause_at_node, _stop_on_run_limit, _validation_stops_run


async def _run_remaining_nodes(ctx: DagRun, start_index: int) -> bool:
    """Run the graph from ``start_index`` on; True when the run stopped early (paused, failed or out of budget)."""
    ordered_node_ids = ctx.graph.ordered_node_ids
    for node_index, node_id in enumerate(ordered_node_ids[start_index:], start=start_index):
        if await _stop_if_run_too_long(ctx, node_id):
            return True
        node = ctx.graph.node_map[node_id]
        if node_id in ctx.existing_node_ids:
            continue
        _set_run_progress(ctx.run, node_index=node_index, node_id=node_id, phase=ctx.mode.start_phase)
        if node_id in ctx.skipped or _all_incoming_skipped(node_id, ctx.graph.edges, ctx.skipped):
            await _skip_node(ctx, node_index, node_id, node)
            continue
        if await _run_node(ctx, node_index, node_id, node):
            return True
    return False


async def _stop_if_run_too_long(ctx: DagRun, node_id: str) -> bool:
    try:
        ensure_run_duration_within_limits(usage=ctx.usage, limits=ctx.limits)
    except FlowRuntimeLimitExceededError as exc:
        await _stop_on_run_limit(
            ctx.db, ctx.run, exc, user_id=ctx.user_id, node_id=node_id,
            node_type=str(ctx.graph.node_map.get(node_id, {}).get("type") or ""),
            detail=dict(ctx.mode.detail) or None, reason=ctx.mode.run_limit_reason,
            commit=ctx.mode.commit_on_limit_stop,
        )
        return True
    return False


async def _skip_node(ctx: DagRun, node_index: int, node_id: str, node: dict[str, Any]) -> None:
    await _persist_skipped_node(ctx.db, ctx.run, ctx.version, node, reason=ctx.mode.skip_reason)
    ctx.skipped.add(node_id)
    _set_run_progress(ctx.run, node_index=node_index, node_id=node_id, phase="skipped")
    if ctx.mode.commit_each_node:
        await _commit_flow_checkpoint(ctx.db, ctx.run)


async def _run_node(ctx: DagRun, node_index: int, node_id: str, node: dict[str, Any]) -> bool:
    """Run one node and record its outcome; True when the run stopped at this node."""
    input_snapshot = _materialize_node_input(
        node_id=node_id,
        edges=ctx.graph.edges,
        outputs=ctx.outputs,
        initial_input=ctx.initial_input,
    )
    attempt = _next_node_attempt(ctx.previous_node_runs, node_id=node_id) if ctx.mode.count_attempts else 1
    node_run = await _start_node_run(
        ctx.db, ctx.run, ctx.version, node, input_snapshot, user_id=ctx.user_id, attempt=attempt,
    )
    update_flow_plan_step(ctx.run, node_id=node_id, status="running", node_run_id=node_run.id)
    try:
        output = await _execute_node(
            ctx.db,
            orchestrator_run=ctx.run,
            node=node,
            input_snapshot=input_snapshot,
            initial_input=ctx.initial_input,
            project_id=ctx.project_id,
            project_config=ctx.project_config,
            user_id=ctx.user_id,
            agent_type=ctx.agent_type,
            limits=ctx.limits,
            usage=ctx.usage,
        )
        return await _record_node_success(ctx, node_index, node_id, node, node_run, output)
    except FlowPausedError as exc:
        await _pause_at_node(ctx, node_index, node_id, node, node_run, input_snapshot, exc)
    except Exception as exc:
        # A fresh run and a resume after approval report a runtime-limit error as budget_exceeded;
        # a resume after an interruption has always reported it as a plain node failure.
        if ctx.mode.catch_node_limits and isinstance(exc, FlowRuntimeLimitExceededError):
            await _fail_node_on_limit(ctx, node_index, node_id, node, node_run, exc)
        else:
            await _fail_node(ctx, node_index, node_id, node, node_run, exc)
    return True


async def _record_node_success(
    ctx: DagRun, node_index: int, node_id: str, node: dict[str, Any], node_run: FlowNodeRun, output: dict[str, Any],
) -> bool:
    selected_targets = _selected_router_targets(node, output, ctx.graph.edges)
    if selected_targets is not None:
        ctx.skipped.update(_unselected_router_targets(node_id, ctx.graph.edges, selected_targets))
    ctx.outputs[node_id] = output
    await _complete_node_run(ctx.db, node_run, node, output, orchestrator_run=ctx.run, user_id=ctx.user_id)
    if ctx.mode.check_validation:
        validation_check = record_validation_outcome(ctx.run, node=node, node_run=node_run, output=output)
        if validation_check is not None and await _validation_stops_run(
            ctx, node_index, node_id, node, node_run, validation_check,
        ):
            return True
    _set_run_progress(ctx.run, node_index=node_index, node_id=node_id, phase="completed")
    if ctx.mode.commit_each_node:
        await _commit_flow_checkpoint(ctx.db, ctx.run, node_run)
    if str(node.get("type") or "") == "output":
        ctx.final_output = output
    return False
