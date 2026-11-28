"""Workflow runs that need a person: Observability → Needs attention and the Inbox."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...time_utils import ensure_utc
from ..project.private_workspace import outside_foreign_private
from .limits import pause_message
from .product_owner_wait import REASON_SPEC_APPROVAL, studio_address
from .records import main_session_id
from .runtime_target.seat_required import ACTION_LABEL, seat_paused
from .states import STATUS_PAUSED, STATUS_WAITING, WAITING_APPROVAL, WAITING_CONFIRMATION, WAITING_WATCH

WAITING_OVERDUE = timedelta(hours=24)
RUNS_LINK = {"tab": "observabilityRuns", "label": "Observability → Runs → Workflow runs"}
# Why the requester reviews their own pull request outside the SCM (``pull_request.reviewer_skipped``).
_OWN_PR_SUBTITLES = {
    "": ("You are the pull request's author, so you were not set as its reviewer; the run waits for the "
         "merge"),
    "reviewer_refused": ("The SCM did not accept you as the pull request's reviewer; review and merge it, the run "
                         "waits for the merge"),
    "requester_unresolved": ("Link your account to be added as reviewer (Profile → Linked accounts); review and merge "
                             "this one, the run waits for the merge"),
}


async def attention_counts(db: AsyncSession, now: datetime, *, viewer_id: str) -> list[tuple[str, int, Any, str]]:
    visible = outside_foreign_private(WorkflowRun.project_id, viewer_id)
    paused = (await db.execute(
        select(func.count(), func.min(WorkflowRun.updated_at)).where(WorkflowRun.status == STATUS_PAUSED, visible)
    )).one()
    overdue = (await db.execute(
        select(func.count(), func.min(WorkflowRun.updated_at)).where(
            WorkflowRun.status == STATUS_WAITING, WorkflowRun.updated_at < now - WAITING_OVERDUE, visible)
    )).one()
    rows = []
    if paused[0]:
        rows.append(("paused", int(paused[0]), paused[1],
                     "Each says why it paused and what to do next; the requester continues, changes the plan or "
                     "aborts."))
    if overdue[0]:
        rows.append(("overdue", int(overdue[0]), overdue[1],
                     "They wait for a confirmation, an approval or an external state for more than a day."))
    return rows


def _web_page(url: Any) -> bool:
    # An SCM answer is never trusted as a link scheme.
    return isinstance(url, str) and url.lower().startswith(("https://", "http://"))


def _iso(value: Any) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


def _waiting_reason(run: WorkflowRun) -> str:
    return str(dict(dict(run.node_state or {}).get("waiting") or {}).get("reason") or "")


async def _responsible_confirms(db: AsyncSession, run: WorkflowRun, user_id: str) -> bool:
    from ...models import User
    from .hitl_actions import _may_confirm

    user = await db.get(User, user_id)
    return run.waiting_kind == WAITING_CONFIRMATION and user is not None and await _may_confirm(db, run, user)


def _paused_title(run: WorkflowRun) -> str:
    return f"{ACTION_LABEL if seat_paused(run) else 'Run paused'}: {run.title}"


async def inbox_items(db: AsyncSession, user_id: str, *, approver: bool = False) -> list[dict[str, Any]]:
    from ..governance.four_eyes import decide_four_eyes

    rows = (await db.execute(
        select(WorkflowRun).where(or_(WorkflowRun.requested_by == user_id, WorkflowRun.responsible_user_id == user_id),
                                  WorkflowRun.status.in_((STATUS_PAUSED, STATUS_WAITING)),
                                  outside_foreign_private(WorkflowRun.project_id, user_id))
        .order_by(WorkflowRun.updated_at.desc()).limit(50)
    )).scalars().all()
    items = []
    for run in rows:
        if run.requested_by != user_id and not await _responsible_confirms(db, run, user_id):
            continue  # a run the person is responsible for: only the confirmation that is theirs to give
        session_id = await main_session_id(db, run)
        link = ({"href": f"/chat?session_id={session_id}", "label": "Decide in the run card"} if session_id
                else RUNS_LINK)
        if run.status == STATUS_PAUSED:
            items.append({
                "kind": "workflow_run_paused", "id": run.id, "title": _paused_title(run),
                "created_at": _iso(run.updated_at), "link": link,
                # The pause's own message, else the catalog's (run.pause.<reason>): why, and what to do next.
                "subtitle": pause_message(run, str(run.pause_reason or ""),
                                          dict(dict(run.node_state or {}).get("pause") or {})),
            })
        elif run.waiting_kind == WAITING_WATCH and dict(run.pull_request or {}).get("reviewer_skipped"):
            # Four-eyes exception: the SCM does not ask the requester to review (author, refused or unlinked account).
            pr = dict(run.pull_request or {})
            items.append({
                "kind": "workflow_run_review_own_pr", "id": run.id, "title": f"Review and merge: {run.title}",
                "created_at": _iso(run.updated_at), "link": {"href": pr["url"], "label": "Open the pull request"}
                if _web_page(pr.get("url")) else link,
                "subtitle": _OWN_PR_SUBTITLES.get(str(pr.get("reviewer_skipped")), _OWN_PR_SUBTITLES[""]),
            })
        elif run.waiting_kind == WAITING_CONFIRMATION and _waiting_reason(run) == REASON_SPEC_APPROVAL:
            items.append({
                "kind": "workflow_run_spec_approval", "id": run.id, "title": f"Approve the spec: {run.title}",
                "created_at": _iso(run.updated_at), "link": {"href": studio_address(run.id),
                                                             "label": "Open the Spec Studio"},
                "subtitle": "Waiting for spec approval: decide, comment and approve in the Spec Studio",
            })
        elif run.waiting_kind == WAITING_CONFIRMATION:
            subject = str(dict(dict(run.node_state or {}).get("waiting") or {}).get("subject") or "")
            items.append({
                "kind": "workflow_run_confirmation", "id": run.id, "title": f"Confirm: {run.title}",
                "created_at": _iso(run.updated_at), "link": link,
                "subtitle": f"Your confirmation ({subject.replace('_', ' ') or 'next step'}) lets the run go on",
            })
    if approver:
        waiting = (await db.execute(
            select(WorkflowRun).where(WorkflowRun.status == STATUS_WAITING,
                                      WorkflowRun.waiting_kind == WAITING_APPROVAL)
            .order_by(WorkflowRun.updated_at.desc()).limit(50)
        )).scalars().all()
        for run in waiting:
            if (await decide_four_eyes(db, run.requested_by, user_id, authors=[run.requested_by])).approved:
                items.append({
                    "kind": "workflow_run_approval", "id": run.id, "title": f"Approve: {run.title}",
                    "created_at": _iso(run.updated_at), "link": RUNS_LINK,
                    "subtitle": "A workflow run waits for your approval (four-eyes)",
                })
    return items


__all__ = ["RUNS_LINK", "attention_counts", "inbox_items"]
