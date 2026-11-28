"""A failed platform action the requester can fix: the run pauses instead of ending."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun
from ...time_utils import utc_now
from .documentation import s1_graph as s1
from .graph import FAILED, NODE_PLATFORM_ACTION, PhasedGraph, PhasedNode, route_values
from .platform.dispatch import (
    CLASS_ALREADY_EXISTS,
    CLASS_BRANCH_CONFLICT,
    CLASS_ENVIRONMENT_NOT_READY,
    CLASS_EXTERNAL,
    CLASS_INVALID,
    CLASS_NOT_CONFIGURED,
    CLASS_PERMISSION,
    CLASS_PR_CONFLICT,
    CLASS_SCOPE_MISMATCH,
    CLASS_TRANSIENT,
    CLASS_WORKSPACE_DIRTY,
)
from .records import WorkflowRunError, record_event
from .states import (
    PAUSE_ACTION_FAILED,
    PAUSE_AUDIENCE_UNPROVEN,
    PAUSE_ENVIRONMENT_NOT_READY,
    PAUSE_NEEDS_CONFIGURATION,
    PAUSE_PUBLISH_UNVERIFIED,
    PAUSE_WORKSPACE_DIRTY,
    STATUS_PAUSED,
)

PAUSE_REASON_KEY = "reason"
FAILED_ACTION_KEY = "failed_action"
# The publish & prove failure classes a person can resolve; ``safety`` is not among them.
S1_RECOVERABLE = frozenset({s1.CLASS_NEEDS_CONFIGURATION, s1.CLASS_PUBLISH_UNVERIFIED, s1.CLASS_RECONCILE_INCOMPLETE,
                            s1.CLASS_PROVIDER_UNAVAILABLE, s1.CLASS_PARSE_FAILED, s1.CLASS_INDEX_TIMEOUT,
                            s1.CLASS_AUDIENCE_UNPROVEN, s1.CLASS_PAGE_CHANGED, s1.CLASS_TARGET_DRIFT})
RECOVERABLE = frozenset({CLASS_ALREADY_EXISTS, CLASS_NOT_CONFIGURED, CLASS_PERMISSION, CLASS_TRANSIENT, CLASS_EXTERNAL,
                         CLASS_BRANCH_CONFLICT, CLASS_PR_CONFLICT, CLASS_ENVIRONMENT_NOT_READY,
                         CLASS_WORKSPACE_DIRTY}) | S1_RECOVERABLE
# A failure class with its own pause reason (the run card names it); every other one pauses ``action_failed``.
PAUSE_REASON_OF = {CLASS_ENVIRONMENT_NOT_READY: PAUSE_ENVIRONMENT_NOT_READY,
                   CLASS_WORKSPACE_DIRTY: PAUSE_WORKSPACE_DIRTY,
                   s1.CLASS_NEEDS_CONFIGURATION: PAUSE_NEEDS_CONFIGURATION,
                   s1.CLASS_PUBLISH_UNVERIFIED: PAUSE_PUBLISH_UNVERIFIED,
                   s1.CLASS_RECONCILE_INCOMPLETE: PAUSE_PUBLISH_UNVERIFIED,
                   s1.CLASS_AUDIENCE_UNPROVEN: PAUSE_AUDIENCE_UNPROVEN}
# A publication that may have been sent is retried (reconcile first) at most this often.
PUBLISH_UNVERIFIED_RETRIES = 3
PAUSED_AT_ACTION = frozenset({PAUSE_ACTION_FAILED, *PAUSE_REASON_OF.values()})
ACTION_RETRY = "retry_action"
ACTION_ADOPT_BRANCH = "adopt_branch"
ACTION_NEW_BRANCH = "new_branch"
DECISIONS = frozenset({ACTION_RETRY, ACTION_ADOPT_BRANCH, ACTION_NEW_BRANCH})
EVENT_NOT_RECOVERABLE = "action_failure_not_recoverable"
_BRANCH_NAME = re.compile(r"^(?!-)(?!/)(?!.*\.\.)(?!.*//)(?!.*\.lock$)(?!.*/$)[A-Za-z0-9._/-]{1,200}$")
_CLASS_TEXTS = {
    CLASS_ALREADY_EXISTS: "it already exists",
    CLASS_NOT_CONFIGURED: "something it needs is not configured",
    CLASS_PERMISSION: "the connection lacks a permission or scope",
    CLASS_TRANSIENT: "the service was unavailable",
    CLASS_EXTERNAL: "the service refused it",
    CLASS_BRANCH_CONFLICT: "the branch exists and is not this Work item's own",
    CLASS_PR_CONFLICT: "an earlier run's pull request is still open",
    CLASS_ENVIRONMENT_NOT_READY: "the working folder cannot run the repository's tests yet",
    CLASS_WORKSPACE_DIRTY: "the working folder has uncommitted changes that are not this run's",
    CLASS_SCOPE_MISMATCH: "the write-back definition belongs to another Workspace",
    s1.CLASS_NEEDS_CONFIGURATION: "the publication is not configured",
    s1.CLASS_PUBLISH_UNVERIFIED: "the publication may have been sent but could not be proven",
    s1.CLASS_RECONCILE_INCOMPLETE: "the check for an earlier send did not complete",
    s1.CLASS_PROVIDER_UNAVAILABLE: "Confluence was unavailable",
    s1.CLASS_PARSE_FAILED: "Knowledge refused the published version",
    s1.CLASS_INDEX_TIMEOUT: "Knowledge did not index the published version in time",
    s1.CLASS_AUDIENCE_UNPROVEN: "the audience receipt did not prove the published page",
    s1.CLASS_PAGE_CHANGED: "the page changed since the confirmed version",
    s1.CLASS_TARGET_DRIFT: "the confirmed target changed",
}
_RETRY_LABELS = {CLASS_ENVIRONMENT_NOT_READY: "Retry after fixing the environment",
                 CLASS_WORKSPACE_DIRTY: "Retry after committing or stashing the changes",
                 s1.CLASS_NEEDS_CONFIGURATION: "Retry after configuring it",
                 s1.CLASS_PUBLISH_UNVERIFIED: "Retry (reconcile the earlier send first)",
                 s1.CLASS_RECONCILE_INCOMPLETE: "Retry (reconcile the earlier send first)",
                 s1.CLASS_AUDIENCE_UNPROVEN: "Retry with a new audience check"}


def record_failure(run: WorkflowRun, *, node_id: str, action: str, reason: str, failure_class: str,
                   detail: dict[str, Any] | None = None) -> None:
    entry = int(dict(run.node_state or {}).get("entry") or 0)
    run.context = {**dict(run.context or {}), FAILED_ACTION_KEY: {
        "node_id": node_id, "entry": entry, "action": action, "reason": reason[:500],
        "failure_class": failure_class or CLASS_INVALID, "recoverable": (failure_class or CLASS_INVALID) in RECOVERABLE,
        "detail": dict(detail or {}), "at": utc_now().isoformat()}}


def _failure_for(run: WorkflowRun, graph: PhasedGraph, node: PhasedNode) -> dict[str, Any] | None:
    failure = dict(dict(run.context or {}).get(FAILED_ACTION_KEY) or {})
    entry = int(dict(run.node_state or {}).get("entry") or 0)
    sources = {edge.source for edge in graph.edges if edge.target == node.id and edge.when == FAILED}
    if not failure or failure.get("node_id") not in sources or int(failure.get("entry") or -1) != entry - 1:
        return None
    return failure


async def enter_pause_node(db: AsyncSession, run: WorkflowRun, graph: PhasedGraph, node: PhasedNode) -> bool:
    from .limits import pause_run

    failure = _failure_for(run, graph, node)
    if failure is None or not failure.get("recoverable"):
        record_event(db, run, EVENT_NOT_RECOVERABLE, node_id=node.id, detail={
            "action": (failure or {}).get("action"), "failure_class": (failure or {}).get("failure_class"),
            "reason": (failure or {}).get("reason") or "no failure of this pass was recorded"})
        return False
    action_node = graph.nodes.get(str(failure["node_id"]))
    title = action_node.title if action_node is not None else str(failure["node_id"])
    because = _CLASS_TEXTS.get(str(failure["failure_class"]), "it failed")
    await pause_run(db, run, reason=PAUSE_REASON_OF.get(str(failure["failure_class"]), PAUSE_ACTION_FAILED),
                    actor_id=None, detail={
        "message": f"{title} failed: {because}. {failure.get('reason') or ''}".strip(),
        "action_node_id": failure["node_id"], "action": failure.get("action"),
        "failure_class": failure["failure_class"], "failure": failure,
        "resume": {"kind": "retry_action", "node_id": failure["node_id"]},
    })
    return True


def _paused_failure(run: WorkflowRun) -> dict[str, Any]:
    pause = dict(dict(run.node_state or {}).get("pause") or {})
    if run.status != STATUS_PAUSED or run.pause_reason not in PAUSED_AT_ACTION or not pause.get("action_node_id"):
        raise WorkflowRunError("not_action_failed", "The run is not paused at a failed platform action.")
    return pause


def pause_actions(run: WorkflowRun) -> list[dict[str, Any]]:
    pause = dict(dict(run.node_state or {}).get("pause") or {})
    label = _RETRY_LABELS.get(str(pause.get("failure_class") or ""), "Retry the step")
    actions: list[dict[str, Any]] = [{"key": ACTION_RETRY, "label": label, "input": None}]
    if pause.get("failure_class") == CLASS_BRANCH_CONFLICT:
        detail = dict(dict(pause.get("failure") or {}).get("detail") or {})
        branch = str(detail.get("branch") or "")
        actions.append({"key": ACTION_ADOPT_BRANCH, "label": f"Adopt the existing branch {branch}".strip(),
                        "input": None, "tone": "danger" if detail.get("foreign_commits") else None})
        actions.append({"key": ACTION_NEW_BRANCH, "label": "Use a new branch name",
                        "input": {"name": "branch", "kind": "text", "label": "New branch name",
                                  "default": f"{branch}-2" if branch else ""}})
    actions.append({"key": "change_plan", "label": "Change the plan", "input": None})
    return actions


async def decide(db: AsyncSession, run: WorkflowRun, *, user: User, action: str, body: dict[str, Any]) -> None:
    from .engine import restart_at
    from .pause import record_decision

    pause = _paused_failure(run)
    failure = dict(pause.get("failure") or {})
    detail = dict(failure.get("detail") or {})
    payload: dict[str, Any] = {"action_node_id": pause["action_node_id"], "failure_class": pause.get("failure_class")}
    context = dict(run.context or {})
    if run.pause_reason == PAUSE_PUBLISH_UNVERIFIED and action == ACTION_RETRY:
        retries = dict(context.get("publish_unverified_retries") or {})
        used = int(retries.get(str(pause["action_node_id"])) or 0)
        if used >= PUBLISH_UNVERIFIED_RETRIES:
            raise WorkflowRunError("retry_budget_used", f"The publication was retried {used} times; change the plan "
                                                        "or abort.", 422)
        context["publish_unverified_retries"] = {**retries, str(pause["action_node_id"]): used + 1}
    if action in (ACTION_ADOPT_BRANCH, ACTION_NEW_BRANCH) and pause.get("failure_class") != CLASS_BRANCH_CONFLICT:
        raise WorkflowRunError("not_branch_conflict", "Only a branch conflict offers this choice.", 422)
    if action == ACTION_ADOPT_BRANCH:
        payload.update(branch=detail.get("branch"), head=detail.get("remote_head"),
                       foreign_commits=list(detail.get("foreign_commits") or []))
        # Bound to the head that was shown: a branch that moved since is a conflict again.
        context["branch_adoption_confirmed"] = {"branch": detail.get("branch"), "head": detail.get("remote_head"),
                                                "by": user.id}
    elif action == ACTION_NEW_BRANCH:
        name = str(body.get("branch") or "").strip()
        if not _BRANCH_NAME.match(name) or name == detail.get("branch"):
            raise WorkflowRunError("invalid_branch_name", "Name a new, valid branch (letters, digits, . _ - /).", 422)
        payload["branch"] = name
        context["branch_override"] = name
        context.pop("branch_created", None)
    run.context = context
    record_decision(db, run, kind="pause", subject=str(run.pause_reason or PAUSE_ACTION_FAILED), action=action,
                    payload=payload, user_id=user.id)
    await restart_at(db, run, str(pause["action_node_id"]), actor_id=user.id)


def failure_route_errors(graph: PhasedGraph) -> list[dict[str, str]]:
    from .graph import NODE_PAUSE

    errors: list[dict[str, str]] = []
    for node in graph.nodes.values():
        if node.kind == NODE_PLATFORM_ACTION and FAILED in (route_values(node) or frozenset()) and not any(
                edge.when == FAILED for edge in graph.exits(node.id)):
            errors.append({"code": "missing_failure_route", "message": f"Platform action '{node.id}' needs a 'failed' "
                                                                       "exit (a pause node or an outcome)."})
        if node.kind != NODE_PAUSE:
            continue
        if str(node.config.get(PAUSE_REASON_KEY) or "") != PAUSE_ACTION_FAILED:
            errors.append({"code": "pause_reason",
                           "message": f"Pause '{node.id}' reason must be '{PAUSE_ACTION_FAILED}'."})
        incoming = [edge for edge in graph.edges if edge.target == node.id]
        if not incoming or any(edge.when != FAILED or graph.nodes.get(edge.source) is None
                               or graph.nodes[edge.source].kind != NODE_PLATFORM_ACTION for edge in incoming):
            errors.append({"code": "pause_entry",
                           "message": f"Pause '{node.id}' is entered only through platform actions' 'failed' exits."})
    return errors


__all__ = ["ACTION_ADOPT_BRANCH", "ACTION_NEW_BRANCH", "ACTION_RETRY", "DECISIONS", "PAUSED_AT_ACTION", "RECOVERABLE",
           "S1_RECOVERABLE", "decide",
           "enter_pause_node", "failure_route_errors", "pause_actions", "record_failure"]
