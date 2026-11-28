"""The responsible person of a workflow run ("Responsible person and approvals")."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, User, WorkflowRun
from ...models.runtime.secure_work import WorkItem
from .records import WorkflowRunError, lock_run, record_event
from .states import ACTIVE_STATUSES

SOURCE_REQUESTER = "requester"
SOURCE_REPORTER = "reporter"
SOURCE_ASSIGNEE = "assignee"
SOURCE_TAKEN_OVER = "taken_over"
SOURCE_ACCEPTED = "accepted"
SOURCES = frozenset({SOURCE_REQUESTER, SOURCE_REPORTER, SOURCE_ASSIGNEE, SOURCE_TAKEN_OVER, SOURCE_ACCEPTED})
# The automatic start's chain, in order. Each link names the Work item column that carries it.
RESPONSIBLE_CHAIN: tuple[str, ...] = (SOURCE_REPORTER, SOURCE_ASSIGNEE)
_ITEM_FIELDS = {SOURCE_REPORTER: "reporter", SOURCE_ASSIGNEE: "assignee"}

ACTION_TAKE_OVER = "take_over"
TAKE_OVER_ACTION = {"key": ACTION_TAKE_OVER, "label": "Take over (become responsible)", "input": None}
SELF_TAKE_OVER_ACTION = {"key": ACTION_TAKE_OVER, "label": "Take over (decide this run yourself)", "input": None}
EVENT_TAKEN_OVER = "responsible_taken_over"
AUDIT_TAKEN_OVER = "workflow_run.taken_over"


async def _member_named(db: AsyncSession, identifier: str, members: dict[str, User]) -> str | None:
    from ..linked_accounts.resolution import account_names

    wanted = identifier.strip().lower()
    if not wanted or not members:
        return None
    linked = await account_names(db, set(members))
    matches = [user.id for user in members.values() if wanted in {
        str(user.username or "").lower(), str(user.email or "").lower(), *linked.get(user.id, set())} - {""}]
    return matches[0] if len(matches) == 1 else None


async def responsible_for(db: AsyncSession, work_item: WorkItem | None, project_id: str | None, *,
                          chain: tuple[str, ...] = RESPONSIBLE_CHAIN) -> tuple[str, str] | None:
    from .work_roles import workspace_humans

    if work_item is None:
        return None
    members = await workspace_humans(db, project_id or work_item.project_id)
    for source in chain:
        field = _ITEM_FIELDS.get(source)
        user_id = await _member_named(db, str(getattr(work_item, field, None) or ""), members) if field else None
        if user_id:
            return user_id, source
    return None


async def initial_responsible(db: AsyncSession, *, user: User, item: WorkItem | None, project_id: str | None,
                              parent: WorkflowRun | None = None, automatic: bool = False
                              ) -> tuple[str | None, str | None]:
    if parent is not None and parent.responsible_user_id:
        return parent.responsible_user_id, parent.responsible_source
    if automatic:
        resolved = await responsible_for(db, item, project_id)
        return resolved if resolved is not None else (None, None)
    return user.id, SOURCE_REQUESTER


def is_responsible(run: WorkflowRun | None, user: User | None) -> bool:
    return bool(run is not None and user is not None and run.responsible_user_id
                and run.responsible_user_id == user.id)


async def responsible_decider(db: AsyncSession, run: WorkflowRun) -> tuple[str, ...]:
    # A platform admin who only started the run is no default decider outside their Workspaces.
    from ..admin.governance.admin_access_service import is_global_admin
    from .work_roles import active_human, workspace_humans

    user_id = run.responsible_user_id
    if not user_id or await active_human(db, user_id) is None:
        return ()
    if user_id in await workspace_humans(db, run.project_id):
        return (user_id,)
    if run.responsible_source == SOURCE_TAKEN_OVER and await is_global_admin(db, user_id):
        return (user_id,)
    return ()


async def responsible_view(db: AsyncSession, run: WorkflowRun) -> dict[str, Any] | None:
    if not run.responsible_user_id:
        return None
    person = await db.get(User, run.responsible_user_id)
    name = (person.display_name or person.username) if person is not None else None
    return {"user_id": run.responsible_user_id, "display_name": name, "source": run.responsible_source}


async def may_take_over(db: AsyncSession, run: WorkflowRun, user: User) -> bool:
    from ..admin.governance.admin_access_service import is_global_admin
    from .access import run_access

    return await run_access(db, run, user) == "write" or await is_global_admin(db, user.id)


async def may_self_take_over(db: AsyncSession, run: WorkflowRun, user: User) -> bool:
    from ..admin.governance.admin_access_service import is_global_admin
    from .work_roles import workspace_humans

    if not is_responsible(run, user) or run.responsible_source != SOURCE_REQUESTER:
        return False
    return user.id not in await workspace_humans(db, run.project_id) and await is_global_admin(db, user.id)


async def take_over_action(db: AsyncSession, run: WorkflowRun, user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    if not is_responsible(run, user):
        return dict(TAKE_OVER_ACTION)
    return dict(SELF_TAKE_OVER_ACTION) if await may_self_take_over(db, run, user) else None


async def take_over(db: AsyncSession, run: WorkflowRun, *, user: User) -> WorkflowRun:
    from ..attention.stream import nudge_after_commit

    if run.status not in ACTIVE_STATUSES:
        raise WorkflowRunError("run_finished", "The run has ended; there is nothing to take over.", 409)
    if not await may_take_over(db, run, user):
        raise WorkflowRunError("take_over_not_permitted", "Only the requester, the Work item owner or an admin "
                                                          "takes this run over.", 403)
    if is_responsible(run, user) and not await may_self_take_over(db, run, user):
        raise WorkflowRunError("already_responsible", "You are already responsible for this run.", 409)
    run = await lock_run(db, run)
    previous, previous_source = run.responsible_user_id, run.responsible_source
    run.responsible_user_id, run.responsible_source = user.id, SOURCE_TAKEN_OVER
    record_event(db, run, EVENT_TAKEN_OVER, node_id=run.current_node_id, actor_id=user.id,
                 detail={"from": previous, "from_source": previous_source, "to": user.id})
    db.add(AuditLog(user_id=user.id, action=AUDIT_TAKEN_OVER, resource_type="workflow_run", resource_id=run.id,
                    project_id=run.project_id,
                    details={"run_id": run.id, "previous_responsible_user_id": previous,
                             "previous_source": previous_source, "responsible_user_id": user.id}))
    if previous and previous != run.requested_by:
        nudge_after_commit(db, previous, run_id=run.id, event=EVENT_TAKEN_OVER)
    return run


__all__ = [
    "ACTION_TAKE_OVER",
    "AUDIT_TAKEN_OVER",
    "EVENT_TAKEN_OVER",
    "RESPONSIBLE_CHAIN",
    "SOURCES",
    "SOURCE_ACCEPTED",
    "SOURCE_ASSIGNEE",
    "SOURCE_REPORTER",
    "SOURCE_REQUESTER",
    "SELF_TAKE_OVER_ACTION",
    "SOURCE_TAKEN_OVER",
    "TAKE_OVER_ACTION",
    "initial_responsible",
    "is_responsible",
    "may_self_take_over",
    "may_take_over",
    "responsible_decider",
    "responsible_for",
    "responsible_view",
    "take_over",
    "take_over_action",
]
