"""The actions a viewer may take on a run, as closed keys the UI renders."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun
from ..admin.governance.admin_access_service import is_global_admin
from .action_failures import PAUSED_AT_ACTION
from .limits import loop_ceiling
from .pause import MAX_BUDGET_FACTOR, abort_run, change_plan, continue_run, loop_headroom
from .records import WorkflowRunError, record_event
from .states import (
    ACTIVE_STATUSES,
    KIND_PHASED,
    PAUSE_ACTION_FAILED,
    PAUSE_BUDGET_LIMIT,
    PAUSE_CONTENT_BLOCKED,
    PAUSE_ENVIRONMENT_NOT_READY,
    PAUSE_EVIDENCE_UNRESOLVED,
    PAUSE_NEEDS_APPROVAL,
    PAUSE_NEEDS_INPUT,
    PAUSE_PIPELINE_NOT_FOR_HEAD,
    ROUND_LIMIT_REASONS,
    RUNTIME_FAILURE_REASONS,
    STATUS_PAUSED,
)

ACTION_RESUME_IN_NEW_SESSION = "resume_in_new_session"
ACTION_CONTINUE = "continue"
ACTION_CHANGE_PLAN = "change_plan"
ACTION_ABORT = "abort"
ACTION_FOLLOW_UP = "follow_up"
ACTION_TAKE_OVER = "take_over"
_FAILED_ACTION_DECISIONS = frozenset({"retry_action", "adopt_branch", "new_branch"})


def _number_input(name: str, label: str, maximum: int) -> dict[str, Any]:
    return {"name": name, "kind": "number", "min": 1, "max": maximum, "default": 1, "label": label}


# Abort and stop record why (``pause.stop_reason``): the card asks for it.
REASON_INPUT = {"name": "reason", "kind": "text", "label": "Why does the run stop?", "default": "", "required": True}
# Without a note a paused phase can only be run again blind, though the product owner may see what is wrong
# in the screenshots. The note reaches the next pass like a product owner answer.
NOTE_INPUT = {"name": "reason", "kind": "text", "label": "Note for the agent (optional)", "default": "",
              "required": False}


async def _pause_actions(db: AsyncSession, run: WorkflowRun) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    paused_at = dict(dict(run.node_state or {}).get("pause") or {})
    if run.pause_reason == PAUSE_ACTION_FAILED or (run.pause_reason in PAUSED_AT_ACTION
                                                   and paused_at.get("action_node_id")):
        from .action_failures import pause_actions

        return pause_actions(run)
    if run.pause_reason == PAUSE_ENVIRONMENT_NOT_READY:
        # A test runner that could not start in a phase: retry re-enters the phase (a new pass, no loop consumed).
        actions.append({"key": ACTION_CONTINUE, "label": "Retry after fixing the environment", "input": NOTE_INPUT})
        actions.append({"key": ACTION_CHANGE_PLAN, "label": "Change the plan", "input": None})
        return actions
    if run.pause_reason in (PAUSE_CONTENT_BLOCKED, *RUNTIME_FAILURE_REASONS):
        # The Action's agent turn failed: continue runs the phase again (the Action re-drives its turn).
        label = ("Run the phase again (the content may be blocked again)" if run.pause_reason == PAUSE_CONTENT_BLOCKED
                 else "Run the phase again")
        actions.append({"key": ACTION_CONTINUE, "label": label, "input": NOTE_INPUT})
        actions.append({"key": ACTION_CHANGE_PLAN, "label": "Change the plan", "input": None})
        return actions
    if run.pause_reason == PAUSE_NEEDS_INPUT:
        # The run asks a person (which app); the note is the answer, the step re-enters with it.
        options = list(paused_at.get("app_options") or [])
        actions.append({"key": ACTION_CONTINUE, "label": "Continue with this answer", "input": {
            "name": "reason", "kind": "text", "label": "Your answer" + (f" ({', '.join(options)})" if options else ""),
            "default": options[0] if options else "", "required": True}})
        actions.append({"key": ACTION_CHANGE_PLAN, "label": "Change the plan", "input": None})
        return actions
    if run.pause_reason == PAUSE_NEEDS_APPROVAL:
        label = "Approve the change plan" if paused_at.get("kind") == "plan" else f"Approve {paused_at.get('path')}"
        actions.append({"key": ACTION_CONTINUE, "label": label, "input": NOTE_INPUT})
        actions.append({"key": ACTION_CHANGE_PLAN, "label": "Change the plan", "input": None})
        return actions
    if run.pause_reason == PAUSE_PIPELINE_NOT_FOR_HEAD:
        # The push found no green pipeline for its tree, also after one re-run: continue runs the pipeline again.
        actions.append({"key": ACTION_CONTINUE, "label": "Run the pipeline again", "input": None})
        actions.append({"key": ACTION_CHANGE_PLAN, "label": "Change the plan", "input": None})
        return actions
    if run.pause_reason == PAUSE_EVIDENCE_UNRESOLVED:
        # The platform could not match the test evidence: re-check re-enters the node (no loop consumed).
        actions.append({"key": ACTION_CONTINUE, "label": "Re-check the test evidence", "input": None})
        actions.append({"key": ACTION_CHANGE_PLAN, "label": "Change the plan", "input": None})
        return actions
    if run.pause_reason in ROUND_LIMIT_REASONS:
        # The failure card: retry with more iterations, re-clarify, stop; findings out of scope → follow-up.
        headroom = loop_headroom(run, await loop_ceiling(db))
        if headroom:
            actions.append({"key": ACTION_CONTINUE, "label": "Retry",
                            "input": _number_input("k", "More iterations", headroom)})
        if (run.ticket_key or run.work_item_id) and not dict(run.context or {}).get("follow_up_issue"):
            actions.append({"key": ACTION_FOLLOW_UP, "label": "Out of scope: follow-up issue", "input": None})
        actions.append({"key": ACTION_CHANGE_PLAN, "label": "Re-clarify", "input": None})
        return actions
    elif run.pause_reason == PAUSE_BUDGET_LIMIT:
        actions.append({"key": ACTION_CONTINUE, "label": "Continue with more budget",
                        "input": _number_input("k", "Budget × more", MAX_BUDGET_FACTOR)})
    else:
        actions.append({"key": ACTION_CONTINUE, "label": "Continue waiting", "input": None})
    actions.append({"key": ACTION_CHANGE_PLAN, "label": "Change the plan", "input": None})
    return actions


async def available_actions(
    db: AsyncSession, run: WorkflowRun, *, access: str, user: User | None = None
) -> list[dict[str, Any]]:
    if access not in ("read", "write") or run.status not in ACTIVE_STATUSES:
        return []
    from .hitl_actions import decision_actions

    if access == "read":
        from .hitl_actions import authored_decider
        from .responsible import is_responsible

        # A reader decides only what is offered to them: as the node's authored decider or as the run's responsible
        # person.
        offered = await authored_decider(db, run) or is_responsible(run, user)
        return await decision_actions(db, run, user=user) if offered else []
    from .runtime_target.seat_required import seat_paused

    # A seat pause goes on only where the run executes: the runtime action below takes it over.
    actions = await _pause_actions(db, run) if run.status == STATUS_PAUSED and not seat_paused(run) else []
    actions += await decision_actions(db, run, user=user)
    from .responsible import take_over_action

    offered_take_over = await take_over_action(db, run, user)
    if offered_take_over is not None:
        actions.append(offered_take_over)  # write access takes the run over (an admin outside: themselves)
    if user is not None and user.id != run.requested_by:
        # The Work item owner or an admin continues a paused run and an approver decides its approval;
        # the card's abort and "continue in a new chat" stay the requester's.
        return actions
    if run.workflow_kind == KIND_PHASED:  # a phased run's runtime steps (``workspace.prepare``, phases) run there
        from .stalled_action import retry_step_action

        if retry := await retry_step_action(db, run):
            actions.append(retry)
        actions.append(await _runtime_action(db, run, user))
    actions.append({"key": ACTION_ABORT, "label": "Abort the run", "input": dict(REASON_INPUT), "tone": "danger"})
    actions.append({"key": ACTION_RESUME_IN_NEW_SESSION, "label": "Continue in a new chat", "input": None})
    return actions


async def _runtime_action(db: AsyncSession, run: WorkflowRun, user: User | None) -> dict[str, Any]:
    from .runtime_target.seat_required import ACTION_LABEL, seat_paused, takeover_default
    from .runtime_target.switch import ACTION_CHANGE_RUNTIME
    from .runtime_target.target import KIND_SERVER, option_key, stored_target, target_options

    current = stored_target(run) or {"kind": KIND_SERVER}
    options = await target_options(db, user=user) if user is not None else []
    takeover = await takeover_default(db, run, options) if seat_paused(run) else None
    return {"key": ACTION_CHANGE_RUNTIME, "label": ACTION_LABEL if takeover else "Change where the run executes",
            "input": {"name": "runtime_target", "kind": "runtime_target", "label": "Run on", "options": options,
                      "default": takeover or option_key(current)}}


async def _approve_scope(db: AsyncSession, run: WorkflowRun, user: User) -> None:
    # Continue on a needs_approval pause is the person's approval: the plan, or the path joins the scope.
    if run.status != "paused" or run.pause_reason != PAUSE_NEEDS_APPROVAL:
        return
    from .plan_scope import approve

    approved = dict(dict(run.node_state or {}).get("pause") or {})
    approve(run, approved, user_id=user.id)
    record_event(db, run, "plan_scope_approved", node_id=run.current_node_id, actor_id=user.id,
                 detail={key: approved.get(key) for key in ("kind", "path", "classes")})


async def perform_action(db: AsyncSession, run: WorkflowRun, *, user: User, body: dict[str, Any]) -> None:
    from .access import require_run_action

    action = str(body.get("action") or "").strip()
    run = await require_run_action(db, run.id, user, action)
    from ..observability.run_quality_metrics import intervention

    intervention(db, run, action)  # a person acted on the run (counted when it commits)
    if action == ACTION_CONTINUE:
        note = str(body.get("reason") or "").strip()
        if note and run.status == "paused":
            from .po_answers import _note_po_answer, _record_po_answer

            _record_po_answer(run, note, user_id=user.id, replaces=body.get("replaces"))
            await _note_po_answer(db, run, note, user, "pause")
        k = body.get("k", 1)
        await _approve_scope(db, run, user)
        await continue_run(db, run, user=user, k=k, is_admin=await is_global_admin(db, user.id))
    elif action == ACTION_CHANGE_PLAN:
        # The person's reason reaches the re-entered phase like a continue's (e.g. back to
        # reproduce to correct an existing test that asserted the bug; without the reason the agent never knows).
        note = str(body.get("reason") or "").strip()
        if note and run.status == "paused":
            from .po_answers import _note_po_answer, _record_po_answer

            _record_po_answer(run, note, user_id=user.id, replaces=body.get("replaces"))
            await _note_po_answer(db, run, note, user, "pause")
        await change_plan(db, run, user=user, is_admin=await is_global_admin(db, user.id))
    elif action == ACTION_ABORT and user.id != run.requested_by and not await is_global_admin(db, user.id):
        raise WorkflowRunError("not_requester", "Only the run's requester or an admin aborts it.", 403)
    elif action == ACTION_ABORT:
        await abort_run(db, run, user=user, reason=str(body.get("reason") or ""))
    elif action == "change_runtime":
        if user.id != run.requested_by and not await is_global_admin(db, user.id):
            raise WorkflowRunError("not_requester", "Only the run's requester or an admin changes where it runs.", 403)
        from .runtime_target.switch import change_runtime

        await change_runtime(db, run, user=user, raw=body.get("runtime_target"))
    elif action == "regenerate_hands_on_scenarios":
        if not await is_global_admin(db, user.id):
            raise WorkflowRunError("admin_only", "Only a platform admin has the hands-on scenarios written again.", 403)
        from .hands_on.step import regenerate

        regenerate(db, run, user_id=user.id, reason=str(body.get("reason") or ""))
    elif action == "waive_hands_on_scenarios":
        if not await is_global_admin(db, user.id):
            raise WorkflowRunError("admin_only", "Only a platform admin waives hands-on scenarios.", 403)
        from .hands_on.waiver import EVENT_WAIVED, waive

        scenarios = body.get("scenarios") if isinstance(body.get("scenarios"), list) else []
        reason = str(body.get("reason") or "")
        waive(run, scenarios, reason, user_id=user.id)
        record_event(db, run, EVENT_WAIVED, node_id=run.current_node_id, actor_id=user.id,
                     detail={"scenarios": [str(item)[:200] for item in scenarios][:50], "reason": reason[:500]})
    elif action == "retry_step":
        if user.id != run.requested_by and not await is_global_admin(db, user.id):
            raise WorkflowRunError("not_requester", "Only the run's requester or an admin retries the step.", 403)
        from .stalled_action import retry_stalled_step

        await retry_stalled_step(db, run, user=user)
    elif action == ACTION_TAKE_OVER:
        from .responsible import take_over

        await take_over(db, run, user=user)
    elif action == ACTION_FOLLOW_UP:
        from .failure import follow_up_action

        await follow_up_action(db, run, user=user)
    elif action in _FAILED_ACTION_DECISIONS:
        from .action_failures import decide as decide_failed_action

        await decide_failed_action(db, run, user=user, action=action, body=body)
    else:
        from .hitl_decisions import decide

        if not await decide(db, run, user=user, action=action, body=body):
            raise WorkflowRunError("unknown_action", f"'{action}' is not an action of this run now.", 422)


__all__ = [
    "ACTION_ABORT",
    "ACTION_CHANGE_PLAN",
    "ACTION_CONTINUE",
    "NOTE_INPUT",
    "ACTION_RESUME_IN_NEW_SESSION",
    "ACTION_TAKE_OVER",
    "REASON_INPUT",
    "available_actions",
    "perform_action",
]
