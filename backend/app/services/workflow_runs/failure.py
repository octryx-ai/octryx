"""The failure path of a run."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, User, WorkflowRun
from ...models.runtime.secure_work import WorkItem
from ...time_utils import utc_now
from .graph import PhasedEdge
from .records import WorkflowRunError, record_event
from .states import EVENT_WAITING, STATUS_PAUSED, STATUS_RUNNING, STATUS_WAITING, WAITING_TOOL_APPROVAL

# device_timeout_s / device_offline_grace_s: how long a step may wait for its device (``device_silence``).
POLICY_KEYS = frozenset({"comment_per_round", "follow_up_on_loop_limit", "follow_up_issue_type", "device_timeout_s",
                         "device_offline_grace_s"})
DEFAULT_FOLLOW_UP_TYPE = "Task"
EVENT_FAILURE = "failure_path"


def validate_failure_policy(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, dict) or set(raw) - POLICY_KEYS:
        return [{"code": "failure_policy", "message": f"failure_policy keys are: {', '.join(sorted(POLICY_KEYS))}."}]
    return []


async def _policy(db: AsyncSession, run: WorkflowRun) -> dict[str, Any]:
    from ...models.runtime.flow_definition import FlowDefinitionVersion

    version = await db.get(FlowDefinitionVersion, run.flow_definition_version_id or "")
    policy = dict(version.definition_json or {}).get("failure_policy") if version is not None else None
    return dict(policy) if isinstance(policy, dict) else {}


failure_policy = _policy


def _held(outcome: Any) -> bool:
    from .platform.dispatch import APPROVAL_PENDING

    return getattr(outcome, "state", "") == APPROVAL_PENDING and bool(getattr(outcome, "approval_id", None))


def _hold(run: WorkflowRun, outcome: Any, *, side_effect: dict[str, Any], title: str,
          then: dict[str, Any] | None = None) -> None:
    state = dict(run.node_state or {})
    if then is None:
        then = ({"kind": "pause", "reason": run.pause_reason, "pause": state.get("pause")}
                if run.status == STATUS_PAUSED else {"kind": "activate"})
    run.status, run.waiting_kind, run.pause_reason = STATUS_WAITING, WAITING_TOOL_APPROVAL, None
    run.node_state = {**state, "waiting": {
        "kind": WAITING_TOOL_APPROVAL, "title": title, "approval_id": outcome.approval_id,
        "action": side_effect["action"], "side_effect": side_effect, "then": then, "since": utc_now().isoformat()}}
    run.context = {**dict(run.context or {}), "last_approval_id": outcome.approval_id}


async def _round_comment(db: AsyncSession, run: WorkflowRun, edge_id: str, node_id: str | None) -> Any:
    from .platform.jira import comment

    outcome = await comment(db, run, {"text_from": "findings"})
    record_event(db, run, EVENT_FAILURE, node_id=node_id, detail={
        "kind": "round_comment", "edge_id": edge_id, "result": outcome.state, "reason": outcome.reason or None})
    return outcome


async def on_failed_round(db: AsyncSession, run: WorkflowRun, edge: PhasedEdge) -> bool:
    policy = await _policy(db, run)
    if not policy.get("comment_per_round") or not run.ticket_key:
        return False
    outcome = await _round_comment(db, run, edge.id, edge.target)
    if not _held(outcome):
        return False
    _hold(run, outcome, side_effect={"kind": "round_comment", "action": "jira.comment", "edge_id": edge.id},
          title="Comment the failed round on the ticket")
    record_event(db, run, EVENT_WAITING, node_id=run.current_node_id,
                 detail={"waiting_kind": WAITING_TOOL_APPROVAL, "action": "jira.comment"})
    return True


async def create_follow_up(db: AsyncSession, run: WorkflowRun, *, reason: str,
                           then: dict[str, Any] | None = None) -> str | None:
    context = dict(run.context or {})
    existing = str(context.get("follow_up_issue") or "")
    if existing and (context.get("follow_up_linked") or not run.ticket_key):
        return existing
    from .platform.jira import create_issue

    policy = await _policy(db, run)
    outcome = await create_issue(db, run, {
        "issue_type": str(policy.get("follow_up_issue_type") or DEFAULT_FOLLOW_UP_TYPE), "follow_up": True,
        "summary_from": "work_item", "description_from": "findings",
    })
    key = str(dict(run.context or {}).get("follow_up_issue") or "")
    record_event(db, run, EVENT_FAILURE, node_id=run.current_node_id, detail={
        "kind": "follow_up_issue", "trigger": reason, "issue": key or None, "result": outcome.state,
        "reason": outcome.reason or None})
    if _held(outcome):
        _hold(run, outcome, side_effect={"kind": "follow_up", "action": "jira.create_issue", "reason": reason},
              title="Create the follow-up issue", then=then)
        record_event(db, run, EVENT_WAITING, node_id=run.current_node_id,
                     detail={"waiting_kind": WAITING_TOOL_APPROVAL, "action": "jira.create_issue"})
        return None
    return key or None


async def on_loop_limit(db: AsyncSession, run: WorkflowRun, edge: PhasedEdge) -> None:
    policy = await _policy(db, run)
    if policy.get("follow_up_on_loop_limit") and (run.ticket_key or run.work_item_id):
        await create_follow_up(db, run, reason=f"loop_limit:{edge.id}")
    del edge


async def follow_up_action(db: AsyncSession, run: WorkflowRun, *, user: User) -> None:
    if not run.ticket_key and not run.work_item_id:
        raise WorkflowRunError("no_ticket", "The run has no ticket a follow-up issue could name.")
    key = await create_follow_up(db, run, reason="out_of_scope")
    if key is None and run.status != STATUS_WAITING:
        raise WorkflowRunError("follow_up_failed", "Jira did not take the follow-up issue; see the run's history.")
    del user  # held for its tool approval: the run waits and the card offers to allow it


async def resume_side_effect(db: AsyncSession, run: WorkflowRun, approval: Approval) -> None:
    from .engine import rerun_current_node

    waiting = dict(dict(run.node_state or {}).get("waiting") or {})
    side, then = dict(waiting.get("side_effect") or {}), dict(waiting.get("then") or {"kind": "activate"})
    if approval.status == "approved":
        if side.get("kind") == "round_comment":
            outcome = await _round_comment(db, run, str(side.get("edge_id") or ""), run.current_node_id)
            if _held(outcome):
                _hold(run, outcome, side_effect=side, title=str(waiting.get("title") or ""), then=then)
                return
        elif side.get("kind") == "follow_up":
            await create_follow_up(db, run, reason=str(side.get("reason") or ""), then=then)
            held_now = dict(dict(run.node_state or {}).get("waiting") or {}).get("approval_id")
            if held_now and held_now != approval.id:
                return  # held again, by a new approval (e.g. the link comment)
    else:
        record_event(db, run, EVENT_FAILURE, node_id=run.current_node_id, detail={
            "kind": side.get("kind"), "result": "not_allowed" if approval.status == "rejected" else approval.status})
    state = {key: value for key, value in dict(run.node_state or {}).items() if key != "waiting"}
    run.waiting_kind = None
    if then.get("kind") == "pause":
        from .pause_causes import cause_of

        pause = dict(then.get("pause") or {})
        cause, rule = cause_of(str(then.get("reason") or ""), pause)
        run.status, run.pause_reason = STATUS_PAUSED, then.get("reason")
        run.node_state = {**state, "pause": {**pause, "cause": cause, "cause_rule": rule}}
        return
    run.status, run.node_state = STATUS_RUNNING, state
    await rerun_current_node(db, run, actor_id=approval.approved_by)


async def outcome_work_state(db: AsyncSession, run: WorkflowRun, *, outcome: str, config: dict[str, Any]) -> None:
    state = str(config.get("work_state") or ("blocked" if outcome == "blocked" else "")).strip()
    if not state or not run.work_item_id or run.parent_run_id:
        return
    from ..secure_work.lifecycle_transitions import auto_transition_work_item

    item = await db.get(WorkItem, run.work_item_id)
    user = await db.get(User, run.requested_by)
    if item is None or user is None:
        return
    result = await auto_transition_work_item(db, item=item, current_user=user, to_state=state,
                                             reason=f"Workflow run '{run.title}' ended {outcome}.")
    record_event(db, run, EVENT_FAILURE if outcome == "blocked" else "work_state", detail={
        "kind": "work_state", "to_state": state, "result": result.get("status"), "reason": result.get("reason")})


async def failure_view(db: AsyncSession, run: WorkflowRun) -> dict[str, Any] | None:
    if run.status != "paused" or run.pause_reason != "loop_limit":
        return None
    from .platform.texts import findings_text

    del db
    return {"findings": findings_text(run), "follow_up_issue": dict(run.context or {}).get("follow_up_issue"),
            "ticket_key": run.ticket_key}


__all__ = ["create_follow_up", "failure_view", "follow_up_action", "on_failed_round", "on_loop_limit",
           "outcome_work_state", "resume_side_effect", "validate_failure_policy"]
