"""Activating a node: its route value at once, or the run waits at it (a phase, a person, a watch, a child run)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from . import failure
from .engine_context import _WAIT, _set_context
from .gate_evaluation import _evaluate_gate
from .graph import (
    NODE_APPROVAL,
    NODE_CONFIRMATION,
    NODE_CONVERSATION,
    NODE_DECISION,
    NODE_GATE,
    NODE_OUTCOME,
    NODE_PARALLEL,
    NODE_PAUSE,
    NODE_PHASE,
    NODE_PLATFORM_ACTION,
    NODE_REVIEW,
    NODE_START,
    NODE_SUB_WORKFLOW,
    NODE_WATCH,
    SUCCEEDED,
    PhasedGraph,
    PhasedNode,
)
from .octryx.continuation import phase_entered
from .records import WorkflowRunError, record_event
from .run_end import _finish, fail_run
from .states import EVENT_WAITING, STATUS_WAITING, WAITING_APPROVAL, WAITING_CONFIRMATION, WAITING_REPLY, WAITING_WATCH

_WAITING_BY_KIND = {
    NODE_CONVERSATION: WAITING_REPLY,
    NODE_CONFIRMATION: WAITING_CONFIRMATION,
    NODE_APPROVAL: WAITING_APPROVAL,
    NODE_WATCH: WAITING_WATCH,
}


async def _activate(db: AsyncSession, run: WorkflowRun, graph: PhasedGraph, node: PhasedNode,
                    actor_id: str | None) -> Any:
    """The node's route value, or ``_WAIT`` when the run now waits at this node."""
    from .handoff.lifecycle import guard_receiver

    receiver = await guard_receiver(db, run)
    from .size_class.merge import entered as merge_entered

    merged, route = await merge_entered(db, run, node)  # a size class does this phase inside a later one
    if merged:
        return route
    if node.kind == NODE_START:
        return await _activate_start(db, run, graph, receiver)
    if node.kind == NODE_PHASE:
        return await _activate_phase(db, run, node)
    if node.kind == NODE_GATE:
        from .slices.results import refresh_slices

        await refresh_slices(db, run)  # a child that ended without a report is a failed slice
        return await _evaluate_gate(db, run, node)
    if node.kind == NODE_DECISION:
        return await _activate_decision(db, run, graph, node)
    if node.kind == NODE_OUTCOME:
        await failure.outcome_work_state(db, run, outcome=str(node.config.get("outcome")), config=node.config)
        await _finish(db, run, outcome=str(node.config.get("outcome")), actor_id=actor_id)
        return _WAIT
    if node.kind == NODE_PLATFORM_ACTION:
        return await _activate_platform_action(db, run, node)
    if node.kind == NODE_PAUSE:
        from .action_failures import enter_pause_node

        return _WAIT if await enter_pause_node(db, run, graph, node) else None
    if node.kind == NODE_PARALLEL:
        from .teamwork.scheduler import enter as enter_parallel_work

        # The coordinator's plan runs as one session per item; the scheduler resolves the node (done | replan).
        route = await enter_parallel_work(db, run, node, graph=graph)
        return route if route else _WAIT
    if node.kind == NODE_REVIEW:
        from .review.runner import enter_review

        enter_review(db, run, node)  # the review worker runs the reviewer outside this request
        return _WAIT
    if node.kind == NODE_SUB_WORKFLOW:
        from .sub_workflows import start_sub_workflow

        await start_sub_workflow(db, run, node, actor_id=actor_id)
        return _WAIT
    return await _activate_waiting(db, run, node, actor_id)


async def _activate_start(db: AsyncSession, run: WorkflowRun, graph: PhasedGraph, receiver: Any) -> Any:
    """The start node: a workflow that receives a specification starts only from an accepted handoff."""
    from .data_flow import receives_spec

    if receives_spec(graph):
        from .handoff.specification import has_spec_handoff

        if receiver is None or not await has_spec_handoff(db, run):
            raise WorkflowRunError("needs_configuration", "This workflow starts only from an accepted "
                                                          "specification handoff.", 409)
    return None


async def _activate_phase(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> Any:
    """A phase: a fresh pass's evidence, and a device thread continues it without a manual prompt."""
    from .run_memory import entered as memory_entered

    await memory_entered(db, run, node)  # what earlier runs of the app learned, for this pass's brief
    _set_context(run, "evidence", node.id, {"tools": [], "artifacts": [], "turns": 0})
    # A device's change and a four-eyes approval belong to one pass: a new pass never reviews, pushes or
    # deploys on the previous one's.
    earlier = dict(dict(run.context or {}).get("device_change") or {})
    run.context = {key: value for key, value in dict(run.context or {}).items()
                   if key not in ("device_change", "four_eyes")}
    if str(earlier.get("patch") or "").strip():
        # Only for the next pass's contract (``previous_change``): it starts from this change instead of
        # re-reading the repository. Never reviewed, pushed or deployed (that is ``device_change`` alone).
        run.context = {**run.context, "previous_device_change": {"patch": earlier["patch"],
                                                                 "node_id": earlier.get("node_id")}}
    await phase_entered(db, run, node)  # a device thread continues the phase without a manual prompt
    return _WAIT


async def _activate_decision(db: AsyncSession, run: WorkflowRun, graph: PhasedGraph, node: PhasedNode) -> Any:
    from .conditions import ConditionUnavailableError, decision_route

    try:
        value = await decision_route(db, run, graph, node)  # field conditions and the otherwise route
    except ConditionUnavailableError as error:
        await fail_run(db, run, str(error))
        return _WAIT
    _set_context(run, "results", node.id, value)
    return value


async def _activate_platform_action(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> Any:
    from .platform_actions import WAIT, run_platform_action
    from .size_class.steps import skip_entered

    if await skip_entered(db, run, node):  # the run's size class leaves this check out
        return SUCCEEDED

    route = await run_platform_action(db, run, node)
    return _WAIT if route == WAIT else route


async def _activate_waiting(db: AsyncSession, run: WorkflowRun, node: PhasedNode, actor_id: str | None) -> Any:
    """A node that waits for a person or an outside state (a confirmation of an epic's story may pass at once)."""
    if node.kind == NODE_CONFIRMATION:
        from .auto_accept import accept_on_entry
        from .graph import CONFIRMED

        if await accept_on_entry(db, run, node):
            return CONFIRMED  # a story of an epic: the product owner answered once for the epic
    from .hitl import enter_waiting_node

    run.status, run.waiting_kind = STATUS_WAITING, _WAITING_BY_KIND[node.kind]
    await enter_waiting_node(db, run, node, actor_id=actor_id)
    record_event(db, run, EVENT_WAITING, node_id=node.id, detail={"waiting_kind": run.waiting_kind})
    return _WAIT
