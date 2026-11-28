"""``bug.report``: the reporter learns what happened to the bug, wherever they reported it."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkflowRun
from ....models.runtime.secure_work import WorkItem
from ..platform.dispatch import ToolOutcome, dispatch_tool

EVENTS = ("cannot_reproduce", "fixed", "released")
MAX_TEXT = 6000
STATE_OF = {"cannot_reproduce": "clarification", "released": "done"}


def _screens(run: WorkflowRun, key: str, *, passed: bool | None = None) -> list[str]:
    results = dict(dict(run.context or {}).get(key) or {}).get("results") or []
    return [name for item in results if isinstance(item, dict) and (passed is None or item.get("passed") is passed)
            for name in item.get("screenshots") or []][:6]


def _root_cause(run: WorkflowRun) -> str:
    review = dict(dict(run.context or {}).get("review") or {})
    summary = str(review.get("summary") or "")
    marker = summary.lower().find("root cause")
    return summary[marker:marker + 600].strip() if marker >= 0 else summary[:600]


def text_for(run: WorkflowRun, event: str) -> str:
    key = run.ticket_key or run.title
    pr = dict(run.pull_request or {})
    link = str(pr.get("url") or pr.get("html_url") or pr.get("number") or "")
    if event == "cannot_reproduce":
        reproduce = dict(dict(run.context or {}).get("hands_on_reproduce") or {})
        lines = [f"{key}: the bug could not be reproduced on the current version.",
                 str(reproduce.get("reason") or "Every scenario of the bug passed."),
                 "Screenshots of what the app showed: " + (", ".join(_screens(run, "hands_on_reproduce")) or "none"),
                 "Please tell us what differs (steps, data, device, version); the bug is not fixed blindly."]
    elif event == "fixed":
        lines = [f"{key}: fixed, waiting for the merge.", _root_cause(run) or "",
                 f"Pull request: {link}" if link else "",
                 "Before (reproduced): " + (", ".join(_screens(run, "hands_on_reproduce", passed=False)) or "-"),
                 "After (green): " + (", ".join(_screens(run, "hands_on", passed=True)) or "-")]
    else:
        merged = str(pr.get("merge_commit_sha") or pr.get("merge_commit") or dict(run.context or {}).get(
            "head_sha") or "")[:12]
        lines = [f"{key}: fixed in {merged or 'the merged pull request'}" + (f" ({link})" if link else "") + "."]
    return "\n".join(line for line in lines if line)[:MAX_TEXT]


async def _jira_comment(db: AsyncSession, run: WorkflowRun, body: str) -> str:
    from ..platform.jira import _platform_item

    if not run.ticket_key or await _platform_item(db, run) is not None:
        return "no Jira ticket"
    from ...ai_marking import run_marking_facts, with_marker

    outcome = await dispatch_tool(db, run, "add_jira_comment", {
        "ticket_id": run.ticket_key, "body": with_marker(body, await run_marking_facts(db, run))},
        capability_class="deliver")
    return "commented" if outcome.ok else f"comment failed: {outcome.reason}"


async def _work_item(db: AsyncSession, run: WorkflowRun, event: str, body: str) -> str:
    state = STATE_OF.get(event)
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    if item is None or state is None:
        return "no transition"
    from ...secure_work.lifecycle_transitions import auto_transition_work_item

    user = await db.get(User, run.requested_by)
    result = await auto_transition_work_item(db, item=item, current_user=user, to_state=state, reason=body[:1900])
    return str(result.get("status") or "")


async def report(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    event = str(params.get("event") or "")
    if event not in EVENTS:
        return ToolOutcome("failed", reason=f"bug.report needs event in {', '.join(EVENTS)}")
    body = text_for(run, event)
    jira = await _jira_comment(db, run, body)
    item = await _work_item(db, run, event, body)
    from ...team_notification.service import create_notification

    await create_notification(db, user_id=run.requested_by, notification_type=f"bug_{event}",
                              title=body.splitlines()[0][:200], body=body, link=f"/workflow-runs/{run.id}",
                              project_id=run.project_id)
    from ..records import record_event

    record_event(db, run, "bug_reported", node_id=run.current_node_id,
                 detail={"event": event, "jira": jira, "work_item": item, "text": body[:2000]})
    return ToolOutcome("succeeded", {"event": event, "jira": jira, "work_item": item})


__all__ = ["EVENTS", "report", "text_for"]
