"""Jira platform actions of a run: create an issue, comment, move the Work state."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkflowRun
from ....models.runtime.secure_work import WorkItem
from .dispatch import (
    APPROVAL_PENDING,
    CLASS_EXTERNAL,
    CLASS_NOT_CONFIGURED,
    CLASS_SCOPE_MISMATCH,
    FAILED,
    SUCCEEDED,
    ToolOutcome,
    dispatch_tool,
)
from .texts import first_line, run_text


async def _project_key(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> str:
    configured = str(params.get("project_key") or "").strip().upper()
    if configured:
        return configured
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    if item is not None and item.source_project_key:
        return str(item.source_project_key).upper()
    # A run without a Work item (an alert-started run) takes the Jira project its Action names.
    configured = str(dict(run.context or {}).get("jira_project_key") or "").strip().upper()
    return configured or str(run.ticket_key or "").split("-")[0].upper()


async def _platform_item(db: AsyncSession, run: WorkflowRun) -> WorkItem | None:
    from ...secure_work.platform_items import PLATFORM_SOURCE_TYPE

    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    return item if item is not None and str(item.source_type or "") == PLATFORM_SOURCE_TYPE else None


def _skipped(note: str, **extra: Any) -> ToolOutcome:
    return ToolOutcome(SUCCEEDED, {**extra, "status": "skipped", "note": note})


async def create_issue(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    follow_up = bool(params.get("follow_up"))
    if (item := await _platform_item(db, run)) is not None:
        if not run.ticket_key:
            run.ticket_key = str(item.source_key)
        return _skipped("platform Work item: no Jira issue", ticket_id=run.ticket_key)
    if not follow_up and run.ticket_key:
        # The run already has its ticket (a Jira Work item or an earlier step): it is never created twice.
        return ToolOutcome(SUCCEEDED, {"ticket_id": run.ticket_key, "status": "existing"})
    if not follow_up and (adopted := await _earlier_ticket(db, run)) is not None:
        return adopted
    project_key = await _project_key(db, run, params)
    if not project_key:
        return ToolOutcome(FAILED, reason="no Jira project: the run has no Work item, ticket or project_key",
                           failure_class=CLASS_NOT_CONFIGURED)
    context = dict(run.context or {})
    if follow_up and context.get("follow_up_issue"):
        # Created earlier; only its link comment may still be outstanding (it waited for an approval).
        return await _link_follow_up(db, run, str(context["follow_up_issue"]))
    summary = first_line(await run_text(db, run, str(params.get("summary_from") or "work_item"))) or run.title
    description = await run_text(db, run, str(params.get("description_from") or "findings"))
    labels = ["workflow-run"]
    if follow_up and run.ticket_key:
        summary = f"Follow-up of {run.ticket_key}: {summary}"[:240]
        description = f"Follow-up of {run.ticket_key} (workflow run {run.id}).\n\n{description}"
        labels.append("follow-up")
    outcome = await dispatch_tool(db, run, "create_jira_ticket", {
        "project_key": project_key, "summary": summary, "description": description,
        "issue_type": str(params.get("issue_type")), "labels": labels,
    }, capability_class="deliver")
    key = str(outcome.result.get("ticket_id") or "") if outcome.ok else ""
    if outcome.ok and key:
        if follow_up:
            context["follow_up_issue"] = key
            run.context = context
            linked = await _link_follow_up(db, run, key)
            if linked.state != SUCCEEDED:
                return linked  # a held link comment makes the run wait for it as well
        elif not run.ticket_key:
            run.ticket_key = key
    return outcome


async def _earlier_ticket(db: AsyncSession, run: WorkflowRun) -> ToolOutcome | None:
    from ..records import record_event
    from ..succession import earlier_runs

    for earlier in await earlier_runs(db, run, same_repository=False):
        if earlier.ticket_key:
            run.ticket_key = earlier.ticket_key
            run.context = {**dict(run.context or {}), "ticket_adopted_from_run": earlier.id}
            record_event(db, run, "ticket_adopted", node_id=run.current_node_id,
                         detail={"ticket_key": earlier.ticket_key, "from_run": earlier.id})
            return ToolOutcome(SUCCEEDED, {"ticket_id": earlier.ticket_key, "status": "adopted",
                                           "adopted_from_run": earlier.id})
    return None


async def _link_follow_up(db: AsyncSession, run: WorkflowRun, key: str) -> ToolOutcome:
    context = dict(run.context or {})
    if context.get("follow_up_linked") or not run.ticket_key:
        return ToolOutcome(SUCCEEDED, {"ticket_id": key, "status": "existing"})
    from ...ai_marking_tools import platform_text

    with platform_text():
        outcome = await dispatch_tool(db, run, "add_jira_comment", {
            "ticket_id": run.ticket_key, "body": f"Follow-up issue: {key}",
        }, capability_class="deliver")
    if outcome.state == APPROVAL_PENDING:
        return outcome
    run.context = {**dict(run.context or {}), "follow_up_linked": True}  # a failed comment is not retried
    return ToolOutcome(SUCCEEDED, {"ticket_id": key, "status": "created", "link": outcome.state})


async def comment(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    if await _platform_item(db, run) is not None:
        return _skipped("platform Work item: no Jira comment")
    if not run.ticket_key:
        return ToolOutcome(FAILED, reason="the run has no ticket to comment on")
    source = str(params.get("text_from") or "findings")
    body = await run_text(db, run, source)
    if not body:
        return ToolOutcome(FAILED, reason="nothing to comment")
    from ...ai_marking_tools import platform_text

    if source == "work_item":  # the Work item's own (human) text is not agent output
        with platform_text():
            return await dispatch_tool(db, run, "add_jira_comment", {"ticket_id": run.ticket_key, "body": body},
                                       capability_class="deliver")
    from ...ai_marking import run_marking_facts, with_marker

    body = with_marker(body, await run_marking_facts(db, run))
    return await dispatch_tool(db, run, "add_jira_comment", {"ticket_id": run.ticket_key, "body": body},
                               capability_class="deliver")


async def transition(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    from ...secure_work.lifecycle_transitions import auto_transition_work_item

    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    if item is None:
        return ToolOutcome(FAILED, reason="the run has no Work item whose write-back mapping moves Jira")
    if await _platform_item(db, run) is not None:
        return _skipped(f"platform Work item: Jira not involved (Work state {params.get('work_state')!s})")
    user = await db.get(User, run.requested_by)
    state = str(params.get("work_state") or "").strip()
    result = await auto_transition_work_item(db, item=item, current_user=user, to_state=state,
                                             reason=f"Workflow run '{run.title}'.")
    status, why = result.get("status"), result.get("reason")
    if status == "unchanged":
        return ToolOutcome(SUCCEEDED, {"status": "unchanged", "work_state": state})
    if status == "refused":
        return ToolOutcome(FAILED, result, "the write-back definition belongs to another Workspace than the Work item",
                           failure_class=CLASS_SCOPE_MISMATCH)
    if why == "jira_changed_since_sync":
        return ToolOutcome(SUCCEEDED, {**result, "status": "skipped", "work_state": state,
                                       "note": "Jira not moved: the issue changed in Jira since the last sync, "
                                               "and that change stands"})
    if why in ("no_workflow_in_scope", "unknown_state"):
        # No Jira write-back for this state means the team has not asked the platform to move Jira: the run goes on.
        return ToolOutcome(SUCCEEDED, {**result, "status": "skipped", "work_state": state,
                                       "note": f"Jira not moved: no write-back definition knows the Work state "
                                               f"'{state}'"})
    if status != "applied":
        return ToolOutcome(FAILED, result, str(result.get("detail") or "the write-back refused the transition"),
                           failure_class=CLASS_EXTERNAL)
    return ToolOutcome(SUCCEEDED, result)


__all__ = ["comment", "create_issue", "transition"]
