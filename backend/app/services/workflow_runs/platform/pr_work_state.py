"""A run's opened pull request moves its Work item to Review on the board.

Like the coding path (``lifecycle_transitions``: agent start -> development, pull request -> review), a workflow
run moves its Work item at this flow point, so a story's epic-delivery run with its pull request open is in Review
on the board, as epic-delivery says the platform keeps "the work item's status".

An epic is not moved: its run's pull request carries the specification, and its stories are built afterwards, each
with its own pull request. The move is best effort through the write-back mapping (a Jira item follows its configured
definition, a platform item the shared states, a Jira item without a definition Jira's status category,
``jira_default_states``); it never fails the pull request step. The epic of a story moves to development (Jira "In
Progress") when the story starts and when its pull request opens; done stays for the merge (the person merges).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkflowRun
from ....models.runtime.secure_work import WorkItem
from ..records import record_event

EVENT_KIND = "work_state"
STATE_DEVELOPMENT, STATE_REVIEW = "development", "review"  # lifecycle_transitions' keys


async def move_item(db: AsyncSession, run: WorkflowRun, item: WorkItem, user: User, to_state: str,
                    reason: str) -> dict:
    """Move ``item`` through its write-back definition; a Jira item without one moves by Jira's status category
    (``jira_default_states``). The outcome is a ``work_state`` run event."""
    from ...secure_work.jira.jira_default_states import move_by_status_category  # noqa: PLC0415
    from ...secure_work.lifecycle_transitions import auto_transition_work_item  # noqa: PLC0415

    result = await auto_transition_work_item(db, item=item, current_user=user, to_state=to_state, reason=reason)
    if result.get("reason") == "no_workflow_in_scope" and str(item.source_type or "") == "jira":
        result = await move_by_status_category(db, item, current_user=user, to_state=to_state, reason=reason)
    jira = result.get("jira") if isinstance(result.get("jira"), dict) else None
    record_event(db, run, EVENT_KIND, detail={"kind": "work_state", "item": item.source_key, "to_state": to_state,
                                              "result": result.get("status"), "reason": result.get("reason"),
                                              **({"mode": result.get("mode"), "jira": jira} if jira else {})})
    return result


async def _epic_of(db: AsyncSession, item: WorkItem) -> WorkItem | None:
    if not item.epic_key:
        return None
    rows = (await db.execute(select(WorkItem).where(
        WorkItem.source_key == item.epic_key, WorkItem.source_type == item.source_type,
        WorkItem.project_id == item.project_id if item.project_id else WorkItem.project_id.is_(None),
    ))).scalars().all()
    return rows[0] if len(rows) == 1 else None


async def epic_in_progress(db: AsyncSession, run: WorkflowRun, story: WorkItem, user: User | None) -> None:
    """A story of an epic runs: the epic is in development (Jira "In Progress") while its stories run.

    Without it, the epic stayed "To Do" while its stories were built."""
    epic = await _epic_of(db, story) if user is not None else None
    if epic is not None and str(epic.work_state or "") in ("", "intake", "clarification", "ready_for_plan", "planning",
                                                          "plan_review", "ready_for_development"):
        await move_item(db, run, epic, user, STATE_DEVELOPMENT,
                        f"Workflow run '{run.title}' builds its story {story.source_key}.")


async def pull_request_opened(db: AsyncSession, run: WorkflowRun, item: WorkItem, user: User | None) -> None:
    """Move ``item`` to Review (its epic to development) and record the outcomes on the run (``work_state``)."""
    if user is None or str(item.issue_type or "").strip().lower() == "epic":
        return
    await move_item(db, run, item, user, STATE_REVIEW, f"Workflow run '{run.title}' opened its pull request.")
    await epic_in_progress(db, run, item, user)
