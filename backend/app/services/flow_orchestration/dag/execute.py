"""A fresh run of a flow graph, whole or from one node on."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session
from ....models.agent.orchestrator_agent import (
    ORCHESTRATOR_PATTERN_PARALLEL,
    ORCHESTRATOR_PATTERN_SEQUENTIAL,
    ORCHESTRATOR_STATUS_COMPLETED,
    ORCHESTRATOR_STATUS_FAILED,
    OrchestratorAgentRun,
)
from ....models.runtime.flow_definition import FlowDefinitionVersion
from ....time_utils import utc_now
from ...flow_runtime_governance import FlowRuntimeLimits, FlowRuntimeUsage, resolve_flow_runtime_limits
from ...orchestrator_service import create_orchestrator_run
from ..planning import initialize_flow_run_plan
from ..recovery import resolve_flow_run_lease_seconds, set_flow_run_lease_config
from ..validation_loop import (
    finalize_validation_loop,
    initialize_validation_loop,
    resolve_validation_loop_config,
    validation_loop_blocks_completion,
)
from .context import DagRun, LoopMode
from .evidence import _flow_final
from .graph import FlowGraph, _last_output, _reachable_downstream_node_ids, parse_flow_graph
from .loop import _run_remaining_nodes
from .model import RuntimeFlowVersion
from .run_state import (
    _audit_flow_event,
    _commit_flow_checkpoint,
    _serialize_limits,
    _set_run_progress,
    _set_runtime_failure,
    _sync_runtime_acceptance,
)
from .runtime_setup import _load_project_config
from .stops import _stop_if_too_many_nodes

_EXECUTE_MODE = LoopMode(
    detail={},
    start_phase="running",
    skip_reason="Branch was not selected.",
    error_suffix="",
    commit_each_node=True,
    commit_on_limit_stop=False,
    catch_node_limits=True,
    check_validation=True,
    count_attempts=False,
    node_count_reason="Flow run failed before execution because runtime limits were exceeded.",
    run_limit_reason="Flow run failed because runtime limits were exceeded.",
    paused_reason="Flow run is waiting for human review.",
    node_limit_reason="Flow node failed because runtime limits were exceeded.",
    node_failed_reason="Flow node failed before acceptance.",
)


async def execute_v2_flow_dag(
    db: AsyncSession,
    *,
    version: FlowDefinitionVersion,
    parent_session_id: str | None,
    project_id: str | None,
    triggered_by_node_id: str | None,
    initial_input: dict[str, Any] | None,
    user_id: str,
    agent_type: str,
) -> OrchestratorAgentRun:
    graph = _checked_flow_graph(version)
    orchestrator_run = await _create_flow_run(
        db, version=version, graph=graph, parent_session_id=parent_session_id, project_id=project_id,
        triggered_by_node_id=triggered_by_node_id, user_id=user_id, agent_type=agent_type,
    )
    limits = _runtime_limits(version, graph, orchestrator_run)
    usage = FlowRuntimeUsage(started_at=utc_now())
    if await _stop_if_too_many_nodes(
        db, orchestrator_run, node_count=len(graph.nodes), limits=limits, user_id=user_id, mode=_EXECUTE_MODE,
    ):
        return orchestrator_run
    await _record_run_started(db, orchestrator_run, node_count=len(graph.nodes), limits=limits, user_id=user_id)
    ctx = DagRun(
        db=db, run=orchestrator_run, version=version, graph=graph, mode=_EXECUTE_MODE, user_id=user_id,
        agent_type=agent_type, project_id=project_id, project_config=await _load_project_config(db, project_id),
        limits=limits, usage=usage, initial_input=initial_input or {}, outputs={}, skipped=set(),
    )
    if await _run_remaining_nodes(ctx, 0):
        return orchestrator_run
    await _finish_fresh_run(ctx)
    return orchestrator_run


def _checked_flow_graph(version: FlowDefinitionVersion) -> FlowGraph:
    graph = parse_flow_graph(version)
    if not graph.nodes:
        raise ValueError(f"FlowDefinitionVersion {version.id} has no nodes")
    if len(graph.ordered_node_ids) != len({str(node.get("id") or "") for node in graph.nodes}):
        raise ValueError(f"FlowDefinitionVersion {version.id} contains a cycle or invalid node IDs")
    return graph


async def _create_flow_run(
    db: AsyncSession,
    *,
    version: FlowDefinitionVersion,
    graph: FlowGraph,
    parent_session_id: str | None,
    project_id: str | None,
    triggered_by_node_id: str | None,
    user_id: str,
    agent_type: str,
) -> OrchestratorAgentRun:
    pattern_type = (
        ORCHESTRATOR_PATTERN_PARALLEL
        if any(node.get("type") == "parallel" for node in graph.nodes)
        else ORCHESTRATOR_PATTERN_SEQUENTIAL
    )
    session_id = await _ensure_session_exists(
        db, session_id=parent_session_id, user_id=user_id, agent_type=agent_type,
        project_id=project_id, flow_definition_version_id=version.id,
    )
    orchestrator_run = await create_orchestrator_run(
        db,
        session_id=session_id,
        parent_session_id=parent_session_id,
        project_id=project_id,
        pattern_type=pattern_type,
        flow_definition_version_id=version.id,
        flow_node_id=triggered_by_node_id,
        total_steps=len(graph.nodes),
    )
    await db.flush()
    initialize_flow_run_plan(orchestrator_run, nodes=graph.nodes, ordered_node_ids=graph.ordered_node_ids)
    validation_loop_config = resolve_validation_loop_config(
        definition=graph.definition,
        version_runtime_settings=getattr(version, "runtime_settings", {}),
        publish_metadata=getattr(version, "publish_metadata", {}),
    )
    initialize_validation_loop(orchestrator_run, validation_loop_config)
    return orchestrator_run


def _runtime_limits(
    version: FlowDefinitionVersion, graph: FlowGraph, orchestrator_run: OrchestratorAgentRun,
) -> FlowRuntimeLimits:
    # A partial run passes a bare RuntimeFlowVersion, hence getattr for the settings.
    limits = resolve_flow_runtime_limits(
        definition=graph.definition,
        version_runtime_settings=getattr(version, "runtime_settings", {}),
        publish_metadata=getattr(version, "publish_metadata", {}),
    )
    set_flow_run_lease_config(
        orchestrator_run,
        lease_seconds=resolve_flow_run_lease_seconds(
            definition=graph.definition,
            version_runtime_settings=getattr(version, "runtime_settings", {}),
            publish_metadata=getattr(version, "publish_metadata", {}),
        ),
    )
    return limits


async def _record_run_started(
    db: AsyncSession, orchestrator_run: OrchestratorAgentRun, *, node_count: int, limits: FlowRuntimeLimits,
    user_id: str,
) -> None:
    await _audit_flow_event(
        db, user_id=user_id, session_id=orchestrator_run.session_id, action="flow.run_started", run=orchestrator_run,
        node_id="", details={"node_count": node_count, "limits": _serialize_limits(limits)},
    )
    await _sync_runtime_acceptance(
        db, user_id=user_id, session_id=orchestrator_run.session_id, run=orchestrator_run, node_id="",
        reason="Flow run started.",
    )
    await _commit_flow_checkpoint(db, orchestrator_run)


async def _finish_fresh_run(ctx: DagRun) -> None:
    db, run, user_id = ctx.db, ctx.run, ctx.user_id
    ordered_node_ids = ctx.graph.ordered_node_ids
    run.merged_output_json = {
        "final": _flow_final(ctx.final_output or _last_output(ctx.outputs, ordered_node_ids)),
        "nodes": ctx.outputs,
    }
    validation_state = finalize_validation_loop(run)
    if validation_loop_blocks_completion(validation_state):
        await _fail_final_validation(ctx, validation_state)
        return
    run.status = ORCHESTRATOR_STATUS_COMPLETED
    run.completed_at = utc_now()
    await _sync_runtime_acceptance(
        db, user_id=user_id, session_id=run.session_id, run=run, node_id="", reason="Flow run completed.",
    )
    await _audit_flow_event(
        db, user_id=user_id, session_id=run.session_id, action="flow.run_completed", run=run, node_id="",
        details={"tool_calls": ctx.usage.tool_calls},
    )
    _set_run_progress(run, node_index=len(ordered_node_ids), node_id="", phase="completed")
    await _commit_flow_checkpoint(db, run)


async def _fail_final_validation(ctx: DagRun, validation_state: dict[str, Any]) -> None:
    db, run, user_id = ctx.db, ctx.run, ctx.user_id
    required_action = str(validation_state.get("required_action") or "stop")
    run.status = ORCHESTRATOR_STATUS_FAILED
    run.last_error = str(validation_state.get("reason") or "Flow validation did not pass.")
    run.completed_at = utc_now()
    failure = _set_runtime_failure(
        run, None, source="validation_loop", required_action=required_action,
        detail={"validation_loop": validation_state},
    )
    await _audit_flow_event(
        db, user_id=user_id, session_id=run.session_id, action="flow.validation_failed", run=run, node_id="",
        details={**validation_state, "failure": failure},
    )
    _set_run_progress(
        run, node_index=len(ctx.graph.ordered_node_ids), node_id="", phase="failed", reason=run.last_error,
        required_action=required_action,
    )
    await _sync_runtime_acceptance(
        db, user_id=user_id, session_id=run.session_id, run=run, node_id="",
        reason="Flow run failed final validation.",
    )
    await _commit_flow_checkpoint(db, run)


async def _ensure_session_exists(
    db: AsyncSession, *, session_id: str | None, user_id: str, agent_type: str,
    project_id: str | None, flow_definition_version_id: str,
) -> str:
    existing = await db.get(Session, session_id) if session_id else None
    if existing is not None:
        return existing.id
    session = Session(
        id=session_id,
        user_id=user_id,
        project_id=project_id,
        flow_definition_version_id=flow_definition_version_id,
        agent_type=agent_type,
        status="active",
        origin="flow",
        metadata_={"flow_runtime_session": True},
    )
    db.add(session)
    await db.flush()
    return session.id


async def execute_v2_partial_flow_dag(
    db: AsyncSession,
    *,
    version: FlowDefinitionVersion,
    start_node_id: str,
    parent_session_id: str | None,
    project_id: str | None,
    initial_input: dict[str, Any] | None,
    user_id: str,
    agent_type: str,
) -> OrchestratorAgentRun:
    definition = dict(version.definition_json or {})
    nodes = [dict(node) for node in definition.get("nodes") or [] if isinstance(node, dict)]
    edges = [dict(edge) for edge in definition.get("edges") or [] if isinstance(edge, dict)]
    node_ids = {str(node.get("id") or "") for node in nodes}
    if start_node_id not in node_ids:
        raise ValueError(f"Partial run start node not found: {start_node_id}")
    reachable = _reachable_downstream_node_ids(start_node_id, edges)
    partial_definition = {
        **definition,
        "nodes": [node for node in nodes if str(node.get("id") or "") in reachable],
        "edges": [
            edge
            for edge in edges
            if str(edge.get("source_node_id") or edge.get("from_node_id") or edge.get("from") or "") in reachable
            and str(edge.get("target_node_id") or edge.get("to_node_id") or edge.get("to") or "") in reachable
        ],
        "partial_run": {"start_node_id": start_node_id},
    }
    partial_version = RuntimeFlowVersion(id=version.id, definition_json=partial_definition)
    return await execute_v2_flow_dag(
        db,
        version=partial_version,  # type: ignore[arg-type]
        parent_session_id=parent_session_id,
        project_id=project_id,
        triggered_by_node_id=start_node_id,
        initial_input=initial_input or {},
        user_id=user_id,
        agent_type=agent_type,
    )
