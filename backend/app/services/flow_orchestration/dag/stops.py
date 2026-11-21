"""Ways a run stops early: runtime limits, a paused node, a failed node, a failed validation check."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import FlowNodeRun
from ....models.agent.orchestrator_agent import (
    ORCHESTRATOR_STATUS_FAILED,
    ORCHESTRATOR_STATUS_PAUSED,
    OrchestratorAgentRun,
)
from ....time_utils import utc_now
from ...error_facts import error_facts, error_text
from ...flow_runtime_governance import (
    FlowRuntimeLimitExceededError,
    FlowRuntimeLimits,
    ensure_node_count_within_limits,
)
from ...runtime_failure_errors import flow_failure_code
from ..validation_loop import validation_loop_blocks_completion, validation_loop_state
from .context import DagRun, LoopMode
from .model import FlowPausedError
from .node_runs import _fail_node_run, _pause_node_run
from .run_state import (
    _audit_flow_event,
    _commit_flow_checkpoint,
    _serialize_limits,
    _set_run_progress,
    _set_runtime_failure,
    _sync_runtime_acceptance,
)


async def _stop_on_run_limit(
    db: AsyncSession,
    orchestrator_run: OrchestratorAgentRun,
    exc: FlowRuntimeLimitExceededError,
    *,
    user_id: str,
    node_id: str | None,
    node_type: str | None,
    detail: dict[str, Any] | None,
    reason: str | None,
    commit: bool,
) -> None:
    orchestrator_run.status = ORCHESTRATOR_STATUS_FAILED
    orchestrator_run.last_error = str(exc)
    orchestrator_run.completed_at = utc_now()
    failure = _set_runtime_failure(
        orchestrator_run, exc, source="runtime_limits", node_id=node_id, node_type=node_type, detail=detail,
    )
    await _audit_flow_event(
        db,
        user_id=user_id,
        session_id=orchestrator_run.session_id,
        action="flow.budget_exceeded",
        run=orchestrator_run,
        node_id=node_id or "",
        details={"code": exc.code, **exc.details, "failure": failure},
    )
    if reason is not None:
        await _sync_runtime_acceptance(
            db,
            user_id=user_id,
            session_id=orchestrator_run.session_id,
            run=orchestrator_run,
            node_id=node_id or "",
            reason=reason,
        )
    if commit:
        await _commit_flow_checkpoint(db, orchestrator_run)
    else:
        await db.flush()


async def _stop_if_too_many_nodes(
    db: AsyncSession,
    orchestrator_run: OrchestratorAgentRun,
    *,
    node_count: int,
    limits: FlowRuntimeLimits,
    user_id: str,
    mode: LoopMode,
) -> bool:
    try:
        ensure_node_count_within_limits(node_count=node_count, limits=limits)
    except FlowRuntimeLimitExceededError as exc:
        await _stop_on_run_limit(
            db, orchestrator_run, exc, user_id=user_id, node_id=None, node_type=None,
            detail={"node_count": node_count, "limits": _serialize_limits(limits), **mode.detail},
            reason=mode.node_count_reason, commit=mode.commit_on_limit_stop,
        )
        return True
    return False


async def _end_stopped_node(ctx: DagRun, node_run: FlowNodeRun) -> None:
    if ctx.mode.commit_each_node:
        await _commit_flow_checkpoint(ctx.db, ctx.run, node_run)
    else:
        await ctx.db.flush()


async def _pause_at_node(
    ctx: DagRun, node_index: int, node_id: str, node: dict[str, Any], node_run: FlowNodeRun,
    input_snapshot: dict[str, Any], exc: FlowPausedError,
) -> None:
    run = ctx.run
    await _pause_node_run(
        ctx.db, node_run, node, {**exc.output, "input": input_snapshot}, orchestrator_run=run, user_id=ctx.user_id,
    )
    run.status = ORCHESTRATOR_STATUS_PAUSED
    run.last_error = str(exc)
    _set_runtime_failure(
        run, exc, source="approval", node_id=node_id, node_type=str(node.get("type") or ""),
        required_action="human_review", detail=dict(ctx.mode.detail) or None,
    )
    _set_run_progress(
        run, node_index=node_index, node_id=node_id, phase="paused", reason=str(exc), required_action="human_review",
    )
    await _sync_runtime_acceptance(
        ctx.db, user_id=ctx.user_id, session_id=run.session_id, run=run, node_id=node_id,
        reason=ctx.mode.paused_reason,
    )
    await _end_stopped_node(ctx, node_run)


async def _fail_node_on_limit(
    ctx: DagRun, node_index: int, node_id: str, node: dict[str, Any], node_run: FlowNodeRun,
    exc: FlowRuntimeLimitExceededError,
) -> None:
    run = ctx.run
    await _fail_node_run(ctx.db, node_run, node, str(exc), orchestrator_run=run, user_id=ctx.user_id)
    run.status = ORCHESTRATOR_STATUS_FAILED
    run.last_error = str(exc)
    run.completed_at = utc_now()
    failure = _set_runtime_failure(
        run, exc, source="runtime_limits", node_id=node_id, node_type=str(node.get("type") or ""),
        detail=dict(ctx.mode.detail) or None,
    )
    _set_run_progress(run, node_index=node_index, node_id=node_id, phase="failed", reason=str(exc))
    await _audit_flow_event(
        ctx.db, user_id=ctx.user_id, session_id=run.session_id, action="flow.budget_exceeded", run=run,
        node_id=node_id, details={"code": exc.code, **exc.details, "failure": failure},
    )
    await _sync_runtime_acceptance(
        ctx.db, user_id=ctx.user_id, session_id=run.session_id, run=run, node_id=node_id,
        reason=ctx.mode.node_limit_reason,
    )
    await _end_stopped_node(ctx, node_run)


async def _fail_node(
    ctx: DagRun, node_index: int, node_id: str, node: dict[str, Any], node_run: FlowNodeRun, exc: Exception,
) -> None:
    run = ctx.run
    failure_text = error_text(flow_failure_code(exc), exc)
    await _fail_node_run(ctx.db, node_run, node, failure_text, orchestrator_run=run, user_id=ctx.user_id)
    run.status = ORCHESTRATOR_STATUS_FAILED
    run.last_error = f"Node {node_id} failed{ctx.mode.error_suffix}: {failure_text}"
    run.completed_at = utc_now()
    failure = _set_runtime_failure(
        run, exc, source="node_execution", node_id=node_id, node_type=str(node.get("type") or ""),
        detail=dict(ctx.mode.detail) or None,
    )
    _set_run_progress(run, node_index=node_index, node_id=node_id, phase="failed", reason=failure_text)
    await _audit_flow_event(
        ctx.db, user_id=ctx.user_id, session_id=run.session_id, action="flow.run_failed", run=run, node_id=node_id,
        details={**error_facts("flow_node_failed", exc), **ctx.mode.detail, "failure": failure},
    )
    await _sync_runtime_acceptance(
        ctx.db, user_id=ctx.user_id, session_id=run.session_id, run=run, node_id=node_id,
        reason=ctx.mode.node_failed_reason,
    )
    await _end_stopped_node(ctx, node_run)


async def _validation_stops_run(
    ctx: DagRun, node_index: int, node_id: str, node: dict[str, Any], node_run: FlowNodeRun,
    validation_check: dict[str, Any],
) -> bool:
    run = ctx.run
    await _audit_flow_event(
        ctx.db, user_id=ctx.user_id, session_id=run.session_id, action="flow.validation_check_recorded", run=run,
        node_id=node_id, details=validation_check,
    )
    validation_state = validation_loop_state(run)
    if not validation_loop_blocks_completion(validation_state):
        return False
    required_action = str(validation_state.get("required_action") or "stop")
    run.status = ORCHESTRATOR_STATUS_FAILED
    run.last_error = str(validation_state.get("reason") or "Flow validation did not pass.")
    run.completed_at = utc_now()
    failure = _set_runtime_failure(
        run, None, source="validation_loop", node_id=node_id, node_type=str(node.get("type") or ""),
        required_action=required_action, detail={"validation_loop": validation_state},
    )
    _set_run_progress(
        run, node_index=node_index, node_id=node_id, phase="failed", reason=run.last_error,
        required_action=required_action,
    )
    await _audit_flow_event(
        ctx.db, user_id=ctx.user_id, session_id=run.session_id, action="flow.validation_failed", run=run,
        node_id=node_id, details={**validation_state, "failure": failure},
    )
    await _sync_runtime_acceptance(
        ctx.db, user_id=ctx.user_id, session_id=run.session_id, run=run, node_id=node_id,
        reason="Flow run failed validation.",
    )
    await _commit_flow_checkpoint(ctx.db, run, node_run)
    return True
