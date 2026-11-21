"""The phased run engine: a bounded state machine over a phased graph.

The run's cursor is ``current_node_id``. Activating a node either produces a route value at once (start,
gate, decision, platform action, outcome) or makes the run wait: a phase waits for agent turns, a
human-in-the-loop node for a person, a watch for an external state, a sub-workflow for its child run. The
engine then follows the exit for the value; a ``loop`` edge counts its iteration and, at its limit, pauses
the run (``limits``) — it never stops or continues silently.

Only this module moves the cursor. Chat reports a phase turn's check result (:func:`complete_phase_turn`);
people decide waiting nodes through ``hitl`` and ``pause``; observers report watched states.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import FlowDefinition, Session, User, WorkflowRun
from ...models.runtime.flow_definition import FlowDefinitionVersion
from ...models.runtime.secure_work import WorkItem
from ...time_utils import utc_now
from . import failure
from .engine_context import _WAIT, _set_context
from .graph import (
    EDGE_LOOP,
    FAILED,
    NODE_PHASE,
    PhasedEdge,
    PhasedGraph,
    PhasedNode,
    graph_for_run,
    parse_phased_definition,
)
from .graph_validation import validate_phased_definition
from .limits import effective_loop_limit, initial_limits, pause_run
from .node_activation import _activate
from .records import WorkflowRunError, bind_session, record_event, ticket_key_of
from .run_end import fail_run
from .states import (
    EVENT_LOOP,
    EVENT_NODE_ENTERED,
    EVENT_STARTED,
    KIND_PHASED,
    PAUSE_LOOP_LIMIT,
    STATUS_RUNNING,
    started_by,
)

# A guard against an engine bug only: bounded loops already make every run finite.
MAX_TRANSITIONS_PER_STEP = 500


async def published_phased_flow(
    db: AsyncSession, workflow_key: str, project_id: str | None
) -> tuple[FlowDefinition, FlowDefinitionVersion] | None:
    """The published phased flow with ``workflow_key`` in the Workspace (or global), else ``None``."""
    from sqlalchemy import or_, select

    rows = (await db.execute(
        select(FlowDefinition, FlowDefinitionVersion)
        .join(FlowDefinitionVersion, FlowDefinitionVersion.id == FlowDefinition.current_version_id)
        .where(FlowDefinition.key == workflow_key, FlowDefinition.status == "published",
               FlowDefinition.is_active.is_(True), FlowDefinitionVersion.status == "published",
               or_(FlowDefinition.project_id.is_(None), FlowDefinition.project_id == project_id))
    )).all()
    for flow, version in sorted(rows, key=lambda row: 0 if row[0].project_id else 1):
        if dict(version.definition_json or {}).get("execution_kind") == "phased":
            return flow, version
    return None


async def start_phased_run(
    db: AsyncSession, *, user: User, flow: FlowDefinition, version: FlowDefinitionVersion,
    project_id: str | None, item: WorkItem | None, repository: str | None, branch: str | None,
    session: Session | None, parent: WorkflowRun | None = None, parent_node_id: str | None = None,
    ticket_key: str | None = None, context: dict[str, Any] | None = None,
    responsible: tuple[str | None, str | None] | None = None,
) -> WorkflowRun:
    definition = dict(version.definition_json or {})
    report = validate_phased_definition(definition)
    if not report["valid"]:
        raise WorkflowRunError("invalid_phased_workflow", "The phased workflow version is not valid.", 422)
    from .phase_agents import phase_agent_db_errors

    agent_errors = await phase_agent_db_errors(db, definition)
    if agent_errors:
        raise WorkflowRunError("phase_agent_unavailable", agent_errors[0]["message"], 409)
    graph = parse_phased_definition(definition)
    from .fragments.provenance import run_composition, version_provenance

    graph.provenance = version_provenance(version)  # the start path parses its own graph
    from .data_flow import receives_spec

    if receives_spec(graph):
        # This graph consumes an accepted typed spec handoff; it never starts directly (no ticket/branch write).
        raise WorkflowRunError("needs_configuration", "This workflow starts only from an accepted specification "
                                                      "handoff.", 409)
    start = graph.start()
    # ``responsible.initial_responsible``; a direct caller's run has its requester.
    responsible_id, responsible_source = responsible or (user.id, "requester")
    run = WorkflowRun(
        project_id=project_id, workflow_kind=KIND_PHASED, workflow_key=flow.key, title=flow.name,
        flow_definition_version_id=version.id, workflow_version=f"v{version.version}",
        work_item_id=item.id if item is not None else None,
        ticket_key=ticket_key_of(item) or ticket_key, repository=repository, branch=branch,
        pull_request={}, status=STATUS_RUNNING, current_node_id=start.id if start else None, node_state={},
        loop_counters={}, limits={}, budget_usage={}, gate_results={}, context=dict(context or {}),
        requested_by=user.id,
        responsible_user_id=responsible_id, responsible_source=responsible_source,
        parent_run_id=parent.id if parent is not None else None, parent_node_id=parent_node_id,
    )
    db.add(run)
    await db.flush()
    await initial_limits(db, run, graph, item=item)
    record_event(db, run, EVENT_STARTED, node_id=run.current_node_id, actor_id=user.id,
                 detail={"workflow_key": run.workflow_key, "version": run.workflow_version,
                         "runtime_target": dict(run.context or {}).get("runtime_target"),
                         **started_by(run),
                         **({"composition": pins} if (pins := run_composition(version)) else {})})
    from .size_class import classify_at_start

    await classify_at_start(db, run, definition, item)  # the workflow's own size_classes block, if it has one
    if session is not None:
        await bind_session(db, run, session, actor_id=user.id)
    await _run_from(db, run, graph, start, actor_id=user.id)
    return run


async def _enter(db: AsyncSession, run: WorkflowRun, node: PhasedNode, *, iteration: int, actor_id: str | None,
                 graph: PhasedGraph | None = None) -> None:
    from .fragments.provenance import node_provenance
    from .teamwork import work_of

    work = work_of(run)
    if work and run.current_node_id == work.get("node_id") and node.id != run.current_node_id:
        from .teamwork.item_stop import left_node

        await left_node(db, run, actor_id=actor_id)  # items still running stop and resume on the next pass
    entry = int(dict(run.node_state or {}).get("entry") or 0) + 1  # one number per pass through any node
    if node.kind == NODE_PHASE:
        from .wip_reset import note_phase_entry

        note_phase_entry(run, node.id)  # the work as the earlier phases left it (``wip_reset``)
    run.current_node_id = node.id
    run.node_state = {"node_id": node.id, "iteration": iteration, "entry": entry,
                      "entered_at": utc_now().isoformat()}
    run.waiting_kind = None
    record_event(db, run, EVENT_NODE_ENTERED, node_id=node.id, actor_id=actor_id,
                 detail={"kind": node.kind, "iteration": iteration, "entry": entry,
                         **({"fragment": origin} if graph and (origin := node_provenance(graph, node.id)) else {})})
    from .octryx.attribution import moved_to

    await moved_to(db, run)  # the bound sessions' metric attribution follows the phase


def _exit_for(graph: PhasedGraph, node: PhasedNode, value: Any, run: WorkflowRun | None = None) -> PhasedEdge | None:
    from .ci_return import CI_RETURN, ci_return_edge
    from .pipeline_head import ROUTE as PIPELINE_NOT_FOR_HEAD
    from .pipeline_head import rerun_edge

    if value == PIPELINE_NOT_FOR_HEAD:  # a push whose tree the pipeline did not run green on: the pipeline again
        return rerun_edge(run, graph, node)
    if value == CI_RETURN:  # a push with nothing new after a failed CI: the CI loop back to the fix (bounded)
        return ci_return_edge(graph) or _exit_for(graph, node, FAILED)
    exits = graph.exits(node.id)
    if value is None:
        return next((edge for edge in exits if edge.when is None), None)
    return next((edge for edge in exits if edge.when == str(value)), None)


async def _take(db: AsyncSession, run: WorkflowRun, graph: PhasedGraph, edge: PhasedEdge,
                actor_id: str | None) -> PhasedNode | None:
    """Follow ``edge``; a loop edge at its limit pauses the run and returns ``None``."""
    iteration = 1
    if edge.kind == EDGE_LOOP:
        counters = dict(run.loop_counters or {})
        counter = dict(counters.get(edge.id) or {})
        used, limit = int(counter.get("used") or 0), effective_loop_limit(run, edge)
        from .size_class.loops import escalate_at_limit, round_limit

        used = escalate_at_limit(db, run, edge.id, used, limit)  # the run's class out of rounds: escalate
        limit_now = round_limit(run, edge.id, limit)
        if used >= limit_now:
            if limit_now < limit:  # paused at the class's rounds: a person's "more rounds" count from there
                counters[edge.id] = {**counter, "limit": limit_now}
                run.loop_counters = counters
            from .failure_codes import last as last_failure

            failed_last = last_failure(run, edge.source)  # who caused it: the last failure's code (``pause_causes``)
            await pause_run(db, run, reason=PAUSE_LOOP_LIMIT, actor_id=actor_id,
                            detail={"edge_id": edge.id, "used": used, "limit": limit_now,
                                    **({"last_failure": failed_last} if failed_last else {}),
                                    "resume": {"kind": "edge", "edge_id": edge.id}})
            await failure.on_loop_limit(db, run, edge)  # one linked follow-up issue
            return None
        counter.update({"used": used + 1, "limit": limit, "title": edge.title or counter.get("title") or edge.id})
        counters[edge.id] = counter
        run.loop_counters = counters
        iteration = used + 2  # the first pass was iteration 1
        _set_context(run, "carried", edge.target, {"from": edge.source,
                                                   "result": dict(run.gate_results or {}).get(edge.source)})
        record_event(db, run, EVENT_LOOP, node_id=edge.target, actor_id=actor_id,
                     detail={"edge_id": edge.id, "used": used + 1, "limit": limit})
    target = graph.nodes[edge.target]
    await _enter(db, run, target, iteration=iteration, actor_id=actor_id, graph=graph)
    if edge.kind == EDGE_LOOP and await failure.on_failed_round(db, run, edge):
        return None  # the round's comment waits for its tool approval; the grant activates the target
    return target


async def _run_from(db: AsyncSession, run: WorkflowRun, graph: PhasedGraph, node: PhasedNode | None,
                    actor_id: str | None, *, value: Any = None, activate: bool = True) -> None:
    """Activate ``node`` (or route on ``value`` from it) and keep going until the run waits or ends."""
    from .handoff.lifecycle import guard_receiver

    await guard_receiver(db, run)
    if node is None:
        await fail_run(db, run, "The phased workflow has no start node.")
        return
    if activate:
        await _enter(db, run, node, iteration=1, actor_id=actor_id, graph=graph)
        value = await _activate(db, run, graph, node, actor_id)
    for _ in range(MAX_TRANSITIONS_PER_STEP):
        if value is _WAIT or run.status not in (STATUS_RUNNING,):
            return
        edge = _exit_for(graph, node, value, run)
        if edge is None:
            await fail_run(db, run, f"Node '{node.id}' has no exit for '{value}'.")
            return
        target = await _take(db, run, graph, edge, actor_id)
        if target is None:
            return
        node = target
        value = await _activate(db, run, graph, node, actor_id)
    await fail_run(db, run, "The run exceeded the engine's transition guard.")


async def resolve_current_node(db: AsyncSession, run: WorkflowRun, value: Any, *, actor_id: str | None) -> None:
    """The current node produced ``value`` (a phase passed, a person decided): continue from it."""
    from .handoff.lifecycle import guard_receiver

    await guard_receiver(db, run)
    graph = await graph_for_run(db, run)
    node = graph.nodes.get(run.current_node_id or "")
    if node is None:
        await fail_run(db, run, "The run's current node is not in its workflow version.")
        return
    recorded = value
    if node.kind == NODE_PHASE:
        from .conditions import phase_result_values
        from .phase_outputs import phase_result

        if phase_result_values(node):
            recorded = phase_result(run, node)  # a later decision routes on the result the agent recorded
    _set_context(run, "results", node.id, recorded)
    run.status, run.waiting_kind = STATUS_RUNNING, None
    await _run_from(db, run, graph, node, actor_id, value=value, activate=False)


async def rerun_current_node(db: AsyncSession, run: WorkflowRun, *, actor_id: str | None) -> None:
    """Activate the current node again (a platform action whose tool approval was granted) and go on."""
    graph = await graph_for_run(db, run)
    node = graph.nodes.get(run.current_node_id or "")
    if node is None:
        await fail_run(db, run, "The run's current node is not in its workflow version.")
        return
    run.status = STATUS_RUNNING
    value = await _activate(db, run, graph, node, actor_id)
    await _run_from(db, run, graph, node, actor_id, value=value, activate=False)


async def take_pending_edge(db: AsyncSession, run: WorkflowRun, edge_id: str, *, actor_id: str | None) -> None:
    """Continue a run that paused on loop edge ``edge_id`` (after its limit was raised)."""
    from .handoff.lifecycle import guard_receiver

    await guard_receiver(db, run)
    graph = await graph_for_run(db, run)
    edge = next((item for item in graph.edges if item.id == edge_id), None)
    if edge is None:
        await fail_run(db, run, f"The paused loop edge '{edge_id}' is not in the workflow version.")
        return
    run.status, run.pause_reason = STATUS_RUNNING, None
    target = await _take(db, run, graph, edge, actor_id)
    if target is not None:
        value = await _activate(db, run, graph, target, actor_id)
        await _run_from(db, run, graph, target, actor_id, value=value, activate=False)


async def restart_at(db: AsyncSession, run: WorkflowRun, node_id: str, *, actor_id: str | None) -> None:
    """Re-enter ``node_id`` (change plan): the run continues from there."""
    from .handoff.lifecycle import guard_receiver

    await guard_receiver(db, run)
    graph = await graph_for_run(db, run)
    node = graph.nodes.get(node_id)
    run.status, run.pause_reason, run.waiting_kind = STATUS_RUNNING, None, None
    await _run_from(db, run, graph, node, actor_id)


__all__ = ["published_phased_flow", "resolve_current_node", "restart_at", "start_phased_run", "take_pending_edge"]
