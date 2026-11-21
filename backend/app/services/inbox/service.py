"""The personal Inbox.

It lists what the signed-in user can decide, each with a link to the screen that owns the decision; nothing is
decided in the Inbox itself:

- tool approvals of their own sessions → the chat card (a session approval is its owner's consent and only the
  owner can open the chat; other users' stale approvals are on Overview → Needs attention for admins);
- governance reviews (publishing policies, skills, evaluators, strategies, routing and model policies) for a global
  admin who is not the requester, or any requester under the single-admin rule → the publishing page;
- approvals of their own device jobs → the chat thread of the job;
- open clarification questions of their own sessions → the chat thread, where the reply answers it.

Workspace names and usernames are loaded only for the rows listed (the bell polls this).

A governance review the user requested under four-eyes waits on someone else and is listed under
``requested_by_me``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, ClarificationQuestion, DeviceJob, DeviceJobApproval, Project, Session, User
from ...time_utils import ensure_utc
from ..admin.governance.admin_access_service import is_global_admin
from ..governance.approval_rule import APPROVAL_RULE_SINGLE_ADMIN, load_approval_rule

MAX_ITEMS = 50
# Governance review action prefix → the admin page that publishes it.
REVIEW_PAGES = (
    ("policy_set.publish", "cedarPolicies", "Policy set"),
    ("skill.publish", "skills", "Skill"),
    ("model_policy.publish", "providers", "Model policy"),
    # The catalog's review action (``prompt_catalog.governance.publish_approval_action``); a
    # "prompt_catalog" prefix never matches, and a prompt review would open the decisions page.
    ("prompt_template.publish", "promptCatalog", "Prompt"),
)


def _iso(value: Any) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


def _review_page(action: str) -> tuple[str, str]:
    for prefix, tab, label in REVIEW_PAGES:
        if action.startswith(prefix):
            return tab, label
    return "observabilityDecisions", "Review"


def _chat(session_id: str) -> dict[str, str]:
    return {"href": f"/chat?session_id={session_id}", "label": "Open the chat card"}


async def _names(db: AsyncSession, model: Any, column: Any, ids: set[str]) -> dict[str, str]:
    ids = {value for value in ids if value}
    if not ids:
        return {}
    return {key: name for key, name in (await db.execute(select(model.id, column).where(model.id.in_(ids)))).all()}


async def _tool_approval_items(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    tool_approvals = (await db.execute(
        select(Approval, Session).join(Session, Session.id == Approval.session_id)
        .where(Approval.status == "pending", Session.user_id == user.id)
        .order_by(Approval.created_at.desc()).limit(MAX_ITEMS)
    )).all()
    names = await _names(db, Project, Project.name, {session.project_id for _approval, session in tool_approvals})
    for approval, session in tool_approvals:
        items.append({
            "kind": "tool_approval", "id": approval.id, "title": approval.action,
            "created_at": _iso(approval.created_at),
            "subtitle": f"Tool approval · your session · {names.get(session.project_id, 'no Workspace')}",
            "link": _chat(session.id),
        })
    return items


async def _governance_review_items(
    db: AsyncSession, user: User, admin: bool, waiting: list[dict[str, Any]], requested: list[dict[str, Any]]
) -> None:
    single_admin = (await load_approval_rule(db)) == APPROVAL_RULE_SINGLE_ADMIN
    reviews = select(Approval).where(Approval.status == "pending", Approval.session_id.is_(None),
                                     Approval.task_run_id.is_(None),
                                     # A workflow run's approval is listed with the run (below).
                                     ~Approval.action.startswith("workflow_run.approval", autoescape=True))
    if not admin:
        reviews = reviews.where(Approval.requested_by == user.id)
    review_rows = list((await db.execute(reviews.order_by(Approval.created_at.desc()).limit(MAX_ITEMS))).scalars())
    users = await _names(db, User, User.username, {approval.requested_by for approval in review_rows})
    for approval in review_rows:
        tab, label = _review_page(approval.action or "")
        item = {"kind": "governance_review", "id": approval.id, "title": f"Review {label.lower()}: {approval.action}",
                "created_at": _iso(approval.created_at), "link": {"tab": tab, "label": f"Open {label}"}}
        if approval.requested_by == user.id and not single_admin:
            requested.append({**item, "subtitle": "Waiting for another admin (approval rule: four-eyes)"})
        elif admin:
            requester = users.get(approval.requested_by, "")
            waiting.append({**item, "subtitle": f"Governance review · requested by {requester}"})


async def _device_and_question_items(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for device_approval, job in (await db.execute(
        select(DeviceJobApproval, DeviceJob).join(DeviceJob, DeviceJob.id == DeviceJobApproval.job_id)
        .where(DeviceJobApproval.status == "pending", DeviceJobApproval.owner_user_id == user.id)
        .order_by(DeviceJobApproval.created_at.desc()).limit(MAX_ITEMS)
    )).all():
        items.append({
            "kind": "device_approval", "id": device_approval.id, "created_at": _iso(device_approval.created_at),
            "title": f"Device job wants to use {device_approval.tool} in {job.folder}",
            "subtitle": "Your device · decide before it expires", "expires_at": _iso(device_approval.expires_at),
            "link": {"href": f"/chat?session_id={job.session_id}", "label": "Open the device prompt"},
        })

    for question, session in (await db.execute(
        select(ClarificationQuestion, Session).join(Session, Session.id == ClarificationQuestion.session_id)
        .where(ClarificationQuestion.status == "open", Session.user_id == user.id)
        .order_by(ClarificationQuestion.created_at.desc()).limit(MAX_ITEMS)
    )).all():
        items.append({
            "kind": "clarification", "id": question.id, "title": question.question_text[:200],
            "created_at": _iso(question.created_at), "subtitle": "Question from the agent · answer in the thread",
            "link": {"href": f"/chat?session_id={session.id}", "label": "Answer in the thread"},
        })
    return items


async def personal_inbox(db: AsyncSession, user: User) -> dict[str, Any]:
    admin = await is_global_admin(db, user.id)
    waiting: list[dict[str, Any]] = []
    requested: list[dict[str, Any]] = []

    waiting.extend(await _tool_approval_items(db, user))
    await _governance_review_items(db, user, admin, waiting, requested)
    waiting.extend(await _device_and_question_items(db, user))

    # The user's paused workflow runs.
    from ..workflow_runs.attention import inbox_items as workflow_run_items

    waiting.extend(await workflow_run_items(db, user.id, approver=admin))
    from ..workflow_runs.role_inbox import inbox_items as role_decision_items

    waiting.extend(await role_decision_items(db, user))
    from ..workflow_runs.handoff.inbox import inbox_items as handoff_items

    waiting.extend(await handoff_items(db, user))
    from ..workflow_runs.documentation.publish_prove_state import inbox_items as publication_items

    waiting.extend(await publication_items(db, user.id))
    waiting.sort(key=lambda item: item["created_at"] or "", reverse=True)
    return {"waiting": waiting[:MAX_ITEMS], "requested_by_me": requested[:MAX_ITEMS], "count": len(waiting)}
