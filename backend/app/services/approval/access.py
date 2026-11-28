"""Who sees and who decides an approval outside a chat session."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, Project, Session, SessionAccess, SessionCollaborator, UserProject
from ...models.project.task import Task, TaskRun
from ..admin.governance.admin_access_service import is_global_admin
from ..project.private_workspace import hidden_private_ids, refuse_foreign_private, refuse_foreign_private_session
from ..project.service import get_project_access_details
from ..session.resource_access import require_session_resource_access
from .errors import approval_already_resolved
from .resolution_service import decide_pending_approval

APPROVAL_NOT_FOUND_DETAIL = "Approval not found"
REVIEWER_PROJECT_ROLES = frozenset({"admin", "owner"})


async def _reviewer_workspace_ids(db: AsyncSession, user_id: str) -> set[str]:
    access = await get_project_access_details(user_id, db)
    return {str(item["id"]) for item in access if str(item.get("role") or "") in REVIEWER_PROJECT_ROLES}


def is_governance_review(approval: Approval) -> bool:
    return not approval.session_id and not approval.task_run_id


async def _may_handle_governance_review(db: AsyncSession, *, approval: Approval, user_id: str) -> bool:
    if not approval.workspace_id:
        from ..prompt_catalog.scope_rights import owned_workflow_publish_actions  # noqa: PLC0415

        return str(approval.action or "") in await owned_workflow_publish_actions(db, user_id)
    if user_id == approval.requested_by:
        return True
    return str(approval.workspace_id) in await _reviewer_workspace_ids(db, user_id)


def _readable_session_clauses(column, user_id: str) -> list[ColumnElement]:
    now = datetime.utcnow()
    team_projects = (
        select(UserProject.project_id)
        .join(Project, Project.id == UserProject.project_id)
        .where(UserProject.user_id == user_id, Project.access_mode == "team")
    )
    return [
        column.in_(select(Session.id).where(Session.user_id == user_id)),
        column.in_(select(SessionCollaborator.session_id).where(SessionCollaborator.user_id == user_id)),
        column.in_(
            select(SessionAccess.session_id).where(
                SessionAccess.user_id == user_id,
                SessionAccess.expires_at.is_(None) | (SessionAccess.expires_at > now),
            )
        ),
        column.in_(select(Session.id).where(Session.project_id.in_(team_projects))),
    ]


def _writable_session_clause(user_id: str) -> ColumnElement:
    # The decision's session-write rule (``session.collaboration.require_session_access``): an explicit owner-issued
    # write grant opens an approval in a private Workspace too.
    now = datetime.utcnow()
    return or_(
        Approval.session_id.in_(select(Session.id).where(Session.user_id == user_id)),
        Approval.session_id.in_(select(SessionCollaborator.session_id).where(
            SessionCollaborator.user_id == user_id, SessionCollaborator.role == "contributor")),
        Approval.session_id.in_(select(SessionAccess.session_id).where(
            SessionAccess.user_id == user_id, SessionAccess.access_scope.in_(("read_write", "admin")),
            SessionAccess.expires_at.is_(None) | (SessionAccess.expires_at > now))),
    )


async def _may_write_session(db: AsyncSession, session_id: str | None, user_id: str) -> bool:
    from ..session.collaboration import require_session_access  # noqa: PLC0415

    if not session_id:
        return False
    try:
        await require_session_access(db, session_id=session_id, user_id=user_id, require_write=True)
    except HTTPException:
        return False
    return True


async def approval_visibility_clause(db: AsyncSession, user_id: str) -> ColumnElement | None:
    if await is_global_admin(db, user_id):
        hidden = await hidden_private_ids(db, user_id)
        if not hidden:
            return None
        return or_(_writable_session_clause(user_id), and_(
            or_(Approval.session_id.is_(None),
                Approval.session_id.not_in(select(Session.id).where(Session.project_id.in_(sorted(hidden))))),
            or_(Approval.workspace_id.is_(None), Approval.workspace_id.not_in(sorted(hidden))),
        ))
    own_runs = (
        select(TaskRun.id)
        .join(Task, Task.id == TaskRun.task_id)
        .where(
            or_(
                Task.owner_id == user_id,
                TaskRun.started_by == user_id,
                *_readable_session_clauses(TaskRun.session_id, user_id),
            )
        )
    )
    reviewed = await _reviewer_workspace_ids(db, user_id)
    handlers = [Approval.requested_by == user_id]
    if reviewed:
        handlers.append(Approval.workspace_id.in_(sorted(reviewed)))
    governance = and_(
        Approval.session_id.is_(None),
        Approval.task_run_id.is_(None),
        Approval.workspace_id.is_not(None),
        or_(*handlers),
    )
    from ..prompt_catalog.scope_rights import owned_workflow_publish_actions  # noqa: PLC0415

    workflow_texts = await owned_workflow_publish_actions(db, user_id)
    if workflow_texts:  # the reviews of the workflow texts this user's workflows have
        governance = or_(governance, and_(Approval.session_id.is_(None), Approval.task_run_id.is_(None),
                                          Approval.action.in_(workflow_texts)))
    return or_(
        *_readable_session_clauses(Approval.session_id, user_id),
        and_(Approval.session_id.is_(None), Approval.task_run_id.in_(own_runs)),
        governance,
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=APPROVAL_NOT_FOUND_DETAIL)


async def require_sessionless_approval_access(db: AsyncSession, *, approval: Approval, user_id: str) -> None:
    if await is_global_admin(db, user_id):
        if approval.workspace_id and await refuse_foreign_private(db, approval.workspace_id, user_id):
            raise _not_found()
        return
    if not approval.task_run_id:
        if await _may_handle_governance_review(db, approval=approval, user_id=user_id):
            return
        raise _not_found()
    await _require_task_run_access(db, approval=approval, user_id=user_id, require_write=True)


async def _require_task_run_access(db: AsyncSession, *, approval: Approval, user_id: str, require_write: bool) -> None:
    run = await db.get(TaskRun, approval.task_run_id)
    if run is None:
        raise _not_found()
    task = await db.get(Task, run.task_id)
    if user_id == run.started_by or (task is not None and user_id == task.owner_id):
        return
    if not run.session_id:
        raise _not_found()
    await require_session_resource_access(
        db,
        session_id=run.session_id,
        user_id=user_id,
        require_write=require_write,
        not_found_detail=APPROVAL_NOT_FOUND_DETAIL,
    )


async def require_approval_visible(db: AsyncSession, *, approval: Approval | None, user_id: str) -> Approval:
    if approval is None:
        raise _not_found()
    if await is_global_admin(db, user_id):
        if ((approval.workspace_id and await refuse_foreign_private(db, approval.workspace_id, user_id))
                or await refuse_foreign_private_session(db, approval.session_id, user_id)) and not (
                await _may_write_session(db, approval.session_id, user_id)):
            raise _not_found()
        return approval
    if approval.session_id:
        await require_session_resource_access(
            db, session_id=approval.session_id, user_id=user_id, not_found_detail=APPROVAL_NOT_FOUND_DETAIL
        )
        return approval
    if approval.task_run_id:
        await _require_task_run_access(db, approval=approval, user_id=user_id, require_write=False)
        return approval
    if await _may_handle_governance_review(db, approval=approval, user_id=user_id):
        return approval
    raise _not_found()


async def decide_sessionless_approval(
    db: AsyncSession, *, approval: Approval, decider_id: str, decision: str, reason: str | None
) -> Approval:
    if approval.session_id:
        raise _not_found()  # a session approval has its own owner (``decide_session_approval``)
    await require_sessionless_approval_access(db, approval=approval, user_id=decider_id)
    if approval.status != "pending":
        raise approval_already_resolved()
    decided = await decide_pending_approval(
        db, approval_id=approval.id, resolved_by=decider_id, status=decision, reason=reason
    )
    if decided is None:
        raise approval_already_resolved()
    await db.commit()
    return decided


__all__ = [
    "APPROVAL_NOT_FOUND_DETAIL",
    "approval_visibility_clause",
    "decide_sessionless_approval",
    "is_governance_review",
    "require_approval_visible",
    "require_sessionless_approval_access",
]
