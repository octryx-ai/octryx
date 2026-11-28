"""A platform action node: a deterministic server-side step the run takes."""

from __future__ import annotations

import logging
import string
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from .graph import FAILED, SUCCEEDED, PhasedNode
from .platform import catalog
from .platform.dispatch import APPROVAL_PENDING, CLASS_NEEDS_FIX, ToolOutcome, dispatch_tool
from .records import WorkflowRunError, record_event
from .states import EVENT_ACTION, EVENT_WAITING, STATUS_PAUSED, STATUS_WAITING, WAITING_TOOL_APPROVAL

WAIT = "__wait__"
logger = logging.getLogger(__name__)


class _Anchor(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _anchor(run: WorkflowRun) -> dict[str, str]:
    return _Anchor(ticket_key=run.ticket_key or "", branch=run.branch or "", repository=run.repository or "",
                   run_id=run.id, workflow_key=run.workflow_key)


def render_arguments(value: Any, anchor: dict[str, str]) -> Any:
    if isinstance(value, str):
        names = {name for _text, name, _spec, _conv in string.Formatter().parse(value) if name}
        return value.format_map(anchor) if names else value
    if isinstance(value, dict):
        return {key: render_arguments(item, anchor) for key, item in value.items()}
    if isinstance(value, list):
        return [render_arguments(item, anchor) for item in value]
    return value


async def _typed(db: AsyncSession, run: WorkflowRun, key: str, params: dict[str, Any],
                 node: PhasedNode | None = None) -> tuple[ToolOutcome, str]:
    from .documentation.s1_graph import is_s1_action, run_s1_action

    if is_s1_action(key):
        return await run_s1_action(db, run, key, params, node)
    from ..pr_review_bot.actions import is_pr_review_action, run_pr_review_action

    if is_pr_review_action(key):
        return await run_pr_review_action(db, run, key, params)
    from .platform import ci, jira, scm

    if key == catalog.CI_STATUS:
        result = await ci.ci_status(db, run, params)
        route = result.state if result.state in ("succeeded", "failed", "running") else FAILED
        return ToolOutcome(SUCCEEDED if route == "succeeded" else "failed", result.to_dict(), result.reason), route
    from .platform import deploy, scm_comment, work_plan

    if key == catalog.DEPLOY_CONFIGURED:
        return await deploy.configured(db, run)
    if key == catalog.WORK_CREATE_STORIES:
        from .teamwork.stories import create_stories

        outcome = await create_stories(db, run, params)
        return outcome, SUCCEEDED if outcome.ok else FAILED
    if key == catalog.WORK_DRAFT_CHANGE_PLAN:
        outcome = await work_plan.draft_change_plan(db, run)
        return outcome, SUCCEEDED if outcome.ok else FAILED
    if key in (catalog.PUBLISH_SPEC, catalog.PUBLISH_FEATURE):
        from .documentation.auto_pages import HANDLERS

        return await HANDLERS[key](db, run, params)
    if key == catalog.PIPELINE_RUN:
        from .pipeline import start as start_pipeline

        return await start_pipeline(db, run, node)
    if key == catalog.HANDS_ON_RUN:
        from .hands_on.step import start as start_hands_on

        return await start_hands_on(db, run, node)
    if key == catalog.BUG_INTAKE_CHECK:
        from .bugs.intake import intake_check

        return await intake_check(db, run, params)
    if key == catalog.BUG_REPORT:
        from .bugs.report import report

        outcome = await report(db, run, params)
        return outcome, SUCCEEDED if outcome.ok else FAILED
    if key == catalog.WORKSPACE_PREPARE:
        from .workspace.preparation import prepare_workspace

        return await prepare_workspace(db, run, node)
    from .pipeline_head import guard

    refused = await guard(db, run, key, node)
    if refused is not None:
        return refused
    handler = {
        catalog.JIRA_CREATE_ISSUE: jira.create_issue, catalog.JIRA_COMMENT: jira.comment,
        catalog.JIRA_TRANSITION: jira.transition, catalog.SCM_CREATE_BRANCH: scm.create_branch,
        catalog.SCM_PUSH: scm.push, catalog.SCM_OPEN_PR: scm.open_pr, catalog.SCM_CHECKOUT: scm.checkout,
        catalog.DEPLOY_RUN: deploy.run_deploy, catalog.SCM_COMMENT: scm_comment.comment,
    }[key]
    outcome = await handler(db, run, params)
    if outcome.failure_class == CLASS_NEEDS_FIX:
        from .ci_return import CI_RETURN

        return outcome, CI_RETURN
    return outcome, SUCCEEDED if outcome.ok else FAILED


async def _perform(db: AsyncSession, run: WorkflowRun, node: PhasedNode, key: str) -> tuple[ToolOutcome, str]:
    if key:
        return await _typed(db, run, key, dict(node.config.get("params") or {}), node)
    tool = str(node.config.get("tool") or "").strip()
    arguments = render_arguments(dict(node.config.get("arguments") or {}), _anchor(run))
    # A free tool step still needs the project's explicit allow for a high-risk tool; only typed catalog actions are
    # allowed by the published workflow.
    outcome = await dispatch_tool(db, run, tool, arguments,
                                  capability_class=catalog.action_class(node.config), typed_action=False)
    return outcome, (SUCCEEDED if outcome.ok else FAILED)


def _raised(run: WorkflowRun, node: PhasedNode, label: str, error: Exception) -> ToolOutcome:
    # A raised step must follow its failed route, never leave the run running.
    from .platform.dispatch import class_of_exception

    logger.exception("workflow_run.platform_action_raised",
                     extra={"run_id": run.id, "node_id": node.id, "action": label})
    return ToolOutcome(FAILED, {}, f"{type(error).__name__}: {error}"[:500], failure_class=class_of_exception(error))


async def action_skipped(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> None:
    if str(node.config.get("action") or "") == catalog.HANDS_ON_RUN:
        from .hands_on.step import skipped as hands_on_skipped

        await hands_on_skipped(db, run, node)


async def run_platform_action(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> str:
    from .engine_context import _set_context
    from .external_step import pass_key

    idempotency_key = pass_key(run, node.id)
    ledger = dict(dict(run.context or {}).get("action_ledger") or {})
    if idempotency_key in ledger:
        record_event(db, run, EVENT_ACTION, node_id=node.id,
                     detail={**ledger[idempotency_key], "idempotency_key": idempotency_key, "replayed": True})
        return str(ledger[idempotency_key]["result"])
    key = str(node.config.get("action") or "").strip()
    label = key or str(node.config.get("tool") or "").strip()
    from .deferred_action import defer, is_deferred

    if is_deferred(key):
        await defer(db, run, node, key, actor_id=None)
        return WAIT
    try:
        outcome, route = await _perform(db, run, node, key)
    except WorkflowRunError:
        raise  # the engine's own answer (refused, in flight, the run moved on): it says what happened, not a failure
    except Exception as error:  # noqa: BLE001 - recorded as the step's failure below, never swallowed
        outcome, route = _raised(run, node, label, error), FAILED
    if route == WAIT and run.status == STATUS_PAUSED:
        return WAIT
    if route == WAIT:
        record_event(db, run, EVENT_WAITING, node_id=node.id, detail={"action": label, **outcome.result})
        return WAIT
    if outcome.state == APPROVAL_PENDING:
        run.status, run.waiting_kind = STATUS_WAITING, WAITING_TOOL_APPROVAL
        run.context = {**dict(run.context or {}), "last_approval_id": outcome.approval_id}
        state = dict(run.node_state or {})
        run.node_state = {**state, "waiting": {"kind": WAITING_TOOL_APPROVAL, "title": node.title,
                                               "approval_id": outcome.approval_id, "action": label}}
        record_event(db, run, EVENT_WAITING, node_id=node.id,
                     detail={"waiting_kind": WAITING_TOOL_APPROVAL, "action": label})
        return WAIT
    if route == FAILED and outcome.state != SUCCEEDED:
        from .action_failures import record_failure
        from .platform.dispatch import CLASS_INVALID

        # A handler's own precondition failure without a class cannot change by retrying it.
        record_failure(run, node_id=node.id, action=label, reason=outcome.reason,
                       failure_class=outcome.failure_class or CLASS_INVALID, detail=outcome.result.get("conflict"))
    _set_context(run, "actions", node.id, {"action": label, "result": route, "reason": outcome.reason or None,
                                           **({"failure_class": outcome.failure_class or "invalid"}
                                              if route == FAILED else {})})
    _set_context(run, "action_ledger", idempotency_key, {"action": label, "result": route})
    record_event(db, run, EVENT_ACTION, node_id=node.id,
                 detail={"action": label, "result": route, "reason": outcome.reason})
    return route


typed_action = _typed

__all__ = ["WAIT", "render_arguments", "run_platform_action", "typed_action"]
