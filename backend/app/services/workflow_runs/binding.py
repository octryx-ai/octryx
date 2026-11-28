"""A chat turn in a session bound to an active run is governed by the run."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, User, WorkflowRun
from ...time_utils import utc_now
from .records import active_run_for_session, lock_run_id, record_event
from .states import (
    EVENT_DUPLICATE_RESULT_IGNORED,
    EVENT_PHASE_TURN,
    RUN_RESOLUTION_KEY,
    RUN_SELECTION_SOURCE,
    STATUS_HELD,
    STATUS_RUNNING,
)

CHECKS_PASSED = "passed"


def phase_resolution(*, run: WorkflowRun, node_id: str, definition: dict[str, Any]) -> dict[str, Any]:
    contract = dict(definition.get("workflow_contract") or {})
    return {
        "source": "db",
        "status": "matched",
        "selection_source": RUN_SELECTION_SOURCE,
        "workflow_key": run.workflow_key,
        "fallback_reason": None,
        "workflow_id": str(definition.get("workflow_id") or contract.get("workflow_id") or ""),
        "workflow_class": str(definition.get("workflow_class") or contract.get("workflow_class") or ""),
        "policy_id": definition.get("policy_id"),
        "policy_version_id": definition.get("policy_version_id"),
        "priority": None,
        "matched_group_id": None,
        "workflow_contract": contract,
        "tool_policy": dict(definition.get("tool_policy") or {}),
        "safety_constraints": dict(definition.get("safety_constraints") or {}),
        RUN_RESOLUTION_KEY: {"run_id": run.id, "node_id": node_id, "kind": run.workflow_kind,
                             "entry": dict(run.node_state or {}).get("entry")},
    }


def held_resolution(run: WorkflowRun, *, profile_status: str, reason: str) -> dict[str, Any]:
    return {
        "source": RUN_SELECTION_SOURCE,
        "status": STATUS_HELD,
        "profile_status": profile_status,
        "unmatched_reason": reason,
        "workflow_key": run.workflow_key,
        "workflow_id": None,
        "workflow_class": None,
        "policy_id": None,
        "policy_version_id": None,
        "priority": None,
        "matched_group_id": None,
        "workflow_contract": None,
        "tool_policy": None,
        "safety_constraints": None,
        RUN_RESOLUTION_KEY: {"run_id": run.id, "node_id": run.current_node_id, "kind": run.workflow_kind},
    }


async def run_turn_resolution(
    db: AsyncSession, session: Session | None, *, user_message: str
) -> dict[str, Any] | None:
    run = await active_run_for_session(db, session.id if session is not None else None)
    if run is None:
        return None
    from .phase_turns import phased_turn_resolution
    from .teamwork import item_key_of

    if item_key_of(session):
        from .teamwork.binding import item_turn_resolution

        # A parallel_work item works under its own synthetic phase; its turn reports to its item, not the node.
        return await item_turn_resolution(db, run, session)
    return await phased_turn_resolution(db, run, user_message=user_message,
                                        user=await db.get(User, session.user_id))


def run_marker(request_analysis: dict[str, Any] | None) -> dict[str, Any] | None:
    from ..workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

    resolution = (request_analysis or {}).get(ROUTING_RESOLUTION_KEY)
    marker = resolution.get(RUN_RESOLUTION_KEY) if isinstance(resolution, dict) else None
    return marker if isinstance(marker, dict) and marker.get("run_id") else None


def ignore_stale_result(
    db: AsyncSession, run: WorkflowRun, *, node_id: str, entry: Any = None, session_id: str | None = None
) -> None:
    # A phase result can arrive twice (a replayed Stop hook, a retried call); applied to the current node it would
    # resolve the decision card with no value.
    record_event(db, run, EVENT_DUPLICATE_RESULT_IGNORED, node_id=node_id, detail={
        "current_node_id": run.current_node_id, "status": run.status, "entry": entry,
        "current_entry": dict(run.node_state or {}).get("entry"), "session_id": session_id})


CHECK_DETAIL_CHARS = 1500


def failed_checks(results: list[Any]) -> list[dict[str, str]]:
    found = []
    for item in results or []:
        data = item.as_dict() if hasattr(item, "as_dict") else dict(item) if isinstance(item, dict) else {}
        if data.get("blocking") and data.get("outcome") != CHECKS_PASSED:
            found.append({"type": str(data.get("type") or ""), "description": str(data.get("description") or ""),
                          "detail": " ".join(str(data.get("detail") or "").split())[:CHECK_DETAIL_CHARS]})
    return found


def failed_checks_text(failed: list[dict[str, str]]) -> str:
    if not failed:
        return "no blocking check is recorded as failed for this turn"
    return "; ".join(f"{item['description'] or item['type']}: {item['detail']}" if item["detail"]
                     else item["description"] or item["type"] for item in failed)


async def record_phase_turn(
    db: AsyncSession,
    *,
    request_analysis: dict[str, Any] | None,
    session_id: str,
    state: str,
    results: list[Any],
    evidence: Any,
) -> None:
    marker = run_marker(request_analysis)
    if marker is None:
        return
    run = await lock_run_id(db, str(marker["run_id"]))
    node_id = str(marker.get("node_id") or "")
    if (run is None or run.status != STATUS_RUNNING or run.current_node_id != node_id
            or dict(run.node_state or {}).get("entry") != marker.get("entry")):
        # The run moved on, re-entered the node or stopped while the turn ran: a stale or replayed report changes
        # nothing, but leaves a trace.
        if run is not None:
            ignore_stale_result(db, run, node_id=node_id, entry=marker.get("entry"), session_id=session_id)
        return
    failure = getattr(evidence, "environment_failure", None)
    if marker.get("item"):
        from .teamwork.item_results import item_finished

        # An item's turn decides only its item: an environment or evidence problem fails the item (the coordinator
        # re-plans with the reason) instead of pausing the run under the other items.
        unresolved = any(getattr(item, "unresolved", False) and getattr(item, "blocking", False) for item in results)
        failed_env = isinstance(failure, dict) and failure
        reason = (f"the tests could not run: {failure.get('reason') or failure}" if failed_env
                  else "the platform could not judge its test evidence" if unresolved else None)
        await item_finished(db, run, key=str(marker["item"]), session_id=session_id,
                            state="failed" if reason else state, reason=reason)
        return
    if failure:
        from .workspace.readiness import pause_not_ready

        # The tests could not run at all: the environment's failure, not the phase's — no result, no loop.
        await pause_not_ready(db, run, {**failure, "session_id": session_id})
        return
    unresolved = [item for item in results if getattr(item, "unresolved", False) and getattr(item, "blocking", False)]
    from .evidence_pause import deferred_to_pipeline

    if unresolved and await deferred_to_pipeline(db, run, unresolved, node_id=node_id):
        unresolved = []  # the pipeline after the phase judges the tests from its own report
    if unresolved:
        from .evidence_pause import pause_unresolved

        # The platform could not judge the turn's test evidence: its problem, not the phase's — no result, no loop.
        await pause_unresolved(db, run, unresolved, node_id=node_id)
        return
    from .review.artefact_evidence import record_provenance

    await record_provenance(db, run, node_id=node_id, session_id=session_id, evidence=evidence, state=state)
    result = {
        "state": state,
        "results": [item.as_dict() if hasattr(item, "as_dict") else dict(item) for item in results],
        "session_id": session_id,
        "at": utc_now().isoformat(),
    }
    run.gate_results = {**dict(run.gate_results or {}), node_id: result}
    failed = failed_checks(result["results"]) if state != CHECKS_PASSED else []
    record_event(db, run, EVENT_PHASE_TURN, node_id=node_id, detail={
        "state": state, "session_id": session_id, **({"failed_checks": failed} if failed else {})})
    from .phase_turns import complete_phase_turn

    await complete_phase_turn(db, run, node_id=node_id, state=state, evidence=evidence)


__all__ = ["failed_checks", "failed_checks_text", "held_resolution", "ignore_stale_result", "phase_resolution",
           "record_phase_turn", "run_marker", "run_turn_resolution"]
