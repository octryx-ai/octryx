"""Account for a governed phase when the loop exhausts its iterations."""

from __future__ import annotations

from typing import Any

from ....services.workflow_runs.binding import run_marker
from ....services.workflow_runs.records import lock_run_id, main_session_id
from ...core.runtime.turn_execution_binding import bound_turn_started_at, claim_turn_checks_record
from ..response._loop_workflow_checks import record_checks_for_ended_turn


async def record_iteration_ceiling(*, db: Any, session_id: str, state: dict[str, Any],
                                   shared: dict[str, Any]) -> None:
    """Use actual turn evidence and the existing once-only claim; fallback prose proves nothing."""
    analysis = shared.get("request_analysis")
    if run_marker(analysis) is None or bound_turn_started_at(session_id) is None:
        return
    context = shared.get("tool_context")
    await record_checks_for_ended_turn(
        db=db, session_id=session_id, messages=state.get("messages") or [],
        context_snapshot=state.get("context_snapshot") or {}, content="",
        request_analysis=analysis, turn_tool_history=state.get("turn_tool_history") or [],
        sub_agent_depth=int(getattr(context, "sub_agent_depth", 0) or 0),
    )


async def hold_research_context(*, db: Any, session_id: str, request_analysis: dict[str, Any],
                                turn_tool_history: list[dict[str, Any]], reason: str) -> None:
    """A pre-provider research context refusal holds the same pass, without a fabricated phase result."""
    from ....services.workflow_runs.limits import pause_run, refresh_budget_usage
    from ....services.workflow_runs.states import PAUSE_BUDGET_LIMIT, PAUSE_NEEDS_CONFIGURATION, STATUS_RUNNING

    marker = run_marker(request_analysis)
    if marker is None or marker.get("slice") or bound_turn_started_at(session_id) is None:
        return
    run = await lock_run_id(db, str(marker["run_id"]))
    if (run is None or run.status != STATUS_RUNNING or run.current_node_id != marker.get("node_id")
            or dict(run.node_state or {}).get("entry") != marker.get("entry")
            or await main_session_id(db, run) != session_id or not claim_turn_checks_record(session_id)):
        return
    exceeded = await refresh_budget_usage(db, run, tool_calls=len(turn_tool_history))
    detail = {"message": "The current research evidence could not be retained safely. Fix the context configuration, "
                         "then retry this phase.", "reason": reason,
              "resume": {"kind": "restart", "node_id": run.current_node_id}}
    if exceeded:
        detail.update(keys=exceeded, resume={"kind": "stay"})
    await pause_run(db, run, reason=PAUSE_BUDGET_LIMIT if exceeded else PAUSE_NEEDS_CONFIGURATION,
                    actor_id=None, detail=detail)
    await db.commit()
