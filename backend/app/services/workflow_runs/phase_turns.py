"""A phase turn ended or a chat turn arrived in a session bound to a phased run: its evidence and resolution."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun
from ..workflow_checks.evidence_families import records_of
from ..workflow_checks.library import TurnEvidence
from .binding import held_resolution, ignore_stale_result, phase_resolution
from .engine_context import _context, _set_context
from .graph import NODE_PHASE, PASSED, graph_for_run
from .limits import pause_run, refresh_budget_usage
from .phase_contract import phase_definition
from .records import lock_run, record_event
from .states import PAUSE_BUDGET_LIMIT, STATUS_RUNNING, STATUS_WAITING, TERMINAL_STATUSES, WAITING_REPLY
from .test_runs import record_turn_test_runs

# A passed turn of a phase with result_values whose agent recorded none: the phase is not done.
EVENT_PHASE_RESULT_MISSING = "phase_result_missing"
MAX_PHASE_ANSWER = 100_000


def _compact_evidence(evidence: Any) -> dict[str, Any]:
    if not isinstance(evidence, TurnEvidence):
        return {}
    return {
        "tools": [{"name": use.name, "succeeded": use.succeeded} for use in evidence.tools],
        "evidence_records": records_of(evidence.tools),
        "artifacts": [str(item.get("type") or "") for item in evidence.artifacts],
        "cited_count": evidence.cited_count, "source_count": evidence.source_count,
        "verification_state": evidence.verification_state,
        # The whole answer (prepared cleanly, never cut): the
        # card folds long text; the bound only guards the row against a runaway answer.
        "answer": str(evidence.answer or "")[:MAX_PHASE_ANSWER],
    }


async def complete_phase_turn(db: AsyncSession, run: WorkflowRun, *, node_id: str, state: str, evidence: Any) -> None:
    from .handoff.lifecycle import guard_receiver

    await guard_receiver(db, run)
    if run.status != STATUS_RUNNING or run.current_node_id != node_id:
        # A duplicate result after the run moved on must not resolve the node that is current now.
        ignore_stale_result(db, run, node_id=node_id)
        return
    context = _context(run)
    recorded = dict(dict(context.get("evidence") or {}).get(node_id) or {})
    turn = _compact_evidence(evidence)
    recorded["tools"] = [*(recorded.get("tools") or []), *turn.get("tools", [])]
    recorded["evidence_records"] = [*(recorded.get("evidence_records") or []),
                                    *turn.get("evidence_records", [])][-200:]
    recorded["artifacts"] = [*(recorded.get("artifacts") or []), *turn.get("artifacts", [])]
    for key in ("cited_count", "source_count", "verification_state"):
        if turn.get(key) is not None:
            recorded[key] = turn[key]
    recorded["turns"] = int(recorded.get("turns") or 0) + 1
    _set_context(run, "evidence", node_id, recorded)
    if turn.get("answer"):
        # The phase's last answer: a confirmation of a drafted ticket or reproduction shows it as its payload.
        _set_context(run, "answers", node_id, turn["answer"])
    await record_turn_test_runs(db, run, list(getattr(evidence, "test_runs", None) or []), node_id=node_id)
    if state == PASSED:
        from .conditions import phase_result_values
        from .phase_outputs import phase_result

        node = (await graph_for_run(db, run)).nodes.get(node_id)
        if node is not None and phase_result_values(node) and phase_result(run, node) is None:
            # A phase that declares result_values is done only once its agent recorded one of them.
            record_event(db, run, EVENT_PHASE_RESULT_MISSING, node_id=node_id,
                         detail={"result_values": list(phase_result_values(node))})
            state = EVENT_PHASE_RESULT_MISSING
    exceeded = await refresh_budget_usage(db, run, tool_calls=len(turn.get("tools", [])))
    if exceeded:
        # The budget pauses the run; the phase's result is kept and applied when it continues.
        await pause_run(db, run, reason=PAUSE_BUDGET_LIMIT, actor_id=None, detail={
            "keys": exceeded, "resume": {"kind": "phase_passed" if state == PASSED else "stay"},
        })
        if state == PASSED:
            context = _context(run)
            context["last_phase"] = node_id
            run.context = context
        return
    if state != PASSED:
        return
    context = _context(run)
    context["last_phase"] = node_id
    run.context = context
    from .engine import resolve_current_node

    await resolve_current_node(db, run, None, actor_id=None)


async def phased_turn_resolution(
    db: AsyncSession, run: WorkflowRun, *, user_message: str, user: User | None = None
) -> dict[str, Any]:
    from .handoff.lifecycle import guard_receiver
    from .hitl import held_reason, record_reply

    await guard_receiver(db, run)

    if run.status == STATUS_WAITING and run.waiting_kind == WAITING_REPLY:
        run = await lock_run(db, run)
        if run.status == STATUS_WAITING and run.waiting_kind == WAITING_REPLY:
            from .hitl_actions import authored_decider

            if await authored_decider(db, run):
                return held_resolution(
                    run, profile_status="needs_clarification",
                    reason="Answer the current decision card; its question and hash must be confirmed together.")
            await record_reply(db, run, user_message, user=user)
    if run.status == STATUS_RUNNING:
        graph = await graph_for_run(db, run)
        node = graph.nodes.get(run.current_node_id or "")
        if node is not None and node.kind == NODE_PHASE:
            from .phase_outputs import phase_inputs
            from .specification.integration import KINDS, authorized_phase_definition
            from .specification.origin import spec_bound

            definition = phase_definition(run, node)
            if KINDS.intersection(phase_inputs(node)) or await spec_bound(db, run):
                from .specification.lineage import SpecificationUnavailable

                try:
                    definition = await authorized_phase_definition(db, run, node, principal=user)
                except SpecificationUnavailable:
                    return held_resolution(run, profile_status="needs_configuration",
                                           reason="The phase's current specification sources are unavailable.")
            from .octryx.research import research_min_sources, with_research

            # The Workspace's research switch (``device_runs.research_phases``), also on a pinned older version.
            definition = with_research(definition, await research_min_sources(db, run, node), brief=True)
            resolution = phase_resolution(run=run, node_id=node.id, definition=definition)
            from .phase_agent_binding import bind_phase_agent

            return await bind_phase_agent(db, run, node, resolution)
    if run.status in TERMINAL_STATUSES:
        return held_resolution(run, profile_status="needs_clarification", reason="The workflow run has ended.")
    profile_status, reason = held_reason(run)
    return held_resolution(run, profile_status=profile_status, reason=reason)
