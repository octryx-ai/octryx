"""Who may start, read and act on a workflow run."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, User, WorkflowRun
from ...models.project import private_guard
from ...models.runtime.secure_work import WorkItem
from ..access_control import WORKSPACE_NOT_FOUND_MESSAGE
from ..linked_accounts.resolution import account_identifiers
from ..project.private_workspace import foreign_private, is_private, refuse_foreign_private
from ..secure_work.access import work_item_in_scope, work_scope_project_ids
from .records import WorkflowRunError, lock_run
from .responsible import ACTION_TAKE_OVER, is_responsible


def _in_scope(scope: set[str] | None, project_id: str | None) -> bool:
    return scope is None or (bool(project_id) and project_id in scope)


async def _visible(db: AsyncSession, user: User, scope: set[str] | None, project_id: str | None) -> bool:
    if project_id and await refuse_foreign_private(db, project_id, user.id):
        return False
    return _in_scope(scope, project_id)


UNRESOLVED_WORKSPACE_MESSAGE = ("The named Workspace does not exist. A workflow run needs an existing Workspace: "
                                "choose one of your Workspaces and start the run again.")


def workspace_required_error(message: str | None = None) -> WorkflowRunError:
    from ..run_admission.denials import MESSAGES, STATE_NEEDS_CONFIGURATION, WORKSPACE_REQUIRED

    return WorkflowRunError(WORKSPACE_REQUIRED, message or MESSAGES[WORKSPACE_REQUIRED], 409,
                            state=STATE_NEEDS_CONFIGURATION)


def require_start_workspace(project_id: str | None, item: WorkItem | None) -> None:
    if (item is not None and not item.project_id) or (item is None and not project_id):
        raise workspace_required_error()


async def require_start_scope(
    db: AsyncSession, user: User, *, project_id: str | None, item: WorkItem | None
) -> None:
    # The order matters: a foreign Work item never gets a Workspace hint, and a missing or foreign Workspace gets one
    # answer for every caller, so nobody learns whether a foreign Workspace exists.
    from ..run_admission.denials import STATE_NEEDS_CONFIGURATION

    require_start_workspace(project_id, item)
    scope = await work_scope_project_ids(db, user)
    if item is not None and not work_item_in_scope(scope, item):
        raise WorkflowRunError("work_item_scope", "The Work item is outside your Workspace access.", 403)
    workspace = await db.get(Project, project_id) if project_id else None
    if project_id and (workspace is None or foreign_private(workspace, user.id) or not _in_scope(scope, project_id)):
        raise workspace_required_error(UNRESOLVED_WORKSPACE_MESSAGE)
    if item is not None and item.project_id != project_id:
        raise WorkflowRunError("work_item_scope", "The Work item belongs to another Workspace.", 403)
    if is_private(workspace):
        raise WorkflowRunError(private_guard.REASON, "Workflow runs are not available in a private Workspace. "
                               "Choose a shared Workspace and start the run again.")
    if workspace is not None and not workspace.is_active:
        # The model gateway refuses every call of an inactive Workspace (project_context_unresolvable): a run started
        # here could never get past its first phase, so it is refused before anything is written.
        raise WorkflowRunError("workspace_inactive",
                               f"Workspace {workspace.name} is inactive. Activate it under Admin → Workspaces.",
                               state=STATE_NEEDS_CONFIGURATION)


async def require_workspace_view(db: AsyncSession, user: User, project_id: str | None) -> None:
    if project_id and not await _visible(db, user, await work_scope_project_ids(db, user), project_id):
        # The answer of an unknown Workspace: an outsider never learns whether a Workspace exists.
        raise WorkflowRunError("project_not_found", WORKSPACE_NOT_FOUND_MESSAGE, 404)


async def is_work_item_owner(db: AsyncSession, item: WorkItem | None, user: User) -> bool:
    assignee = str(getattr(item, "assignee", None) or "").strip().lower()
    if not assignee:
        return False
    names = {str(user.username or "").lower(), str(user.email or "").lower()}
    names.update(await account_identifiers(db, user.id))
    return assignee in names - {""}


async def run_access(db: AsyncSession, run: WorkflowRun | None, user: User) -> str:
    if run is None:
        return "none"
    scope = await work_scope_project_ids(db, user)
    if run.requested_by == user.id and not (run.project_id and await refuse_foreign_private(db, run.project_id,
                                                                                            user.id)):
        return "write"
    if not await _visible(db, user, scope, run.project_id):
        return "none"
    if scope is None:
        return "write"
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    return "write" if await is_work_item_owner(db, item, user) else "read"


async def require_run(db: AsyncSession, run_id: str, user: User, *, write: bool = False) -> WorkflowRun:
    run = await db.get(WorkflowRun, run_id)
    access = await run_access(db, run, user)
    if access == "none":
        raise WorkflowRunError("unknown_run", "The workflow run does not exist.", 404)
    if write and access != "write":
        raise WorkflowRunError("run_read_only", "Only the requester, the Work item owner or an admin acts on "
                                                "this run.", 403)
    return await lock_run(db, run) if write else run


async def require_run_action(db: AsyncSession, run_id: str, user: User, action: str) -> WorkflowRun:
    # A role grants only its current offered decision, never general Run or execution access.
    run = await require_run(db, run_id, user)
    access = await run_access(db, run, user)
    if action == ACTION_TAKE_OVER and access != "write":
        raise WorkflowRunError("take_over_not_permitted", "Only the requester, the Work item owner or an admin "
                                                          "takes this run over.", 403)
    run = await lock_run(db, run)
    if access == "write":
        return run
    from .hitl_actions import authored_decider, decision_actions

    if not (await authored_decider(db, run) or is_responsible(run, user)):
        raise WorkflowRunError("run_read_only", "This run is read-only for you.", 403)
    offered = await decision_actions(db, run, user=user)
    if action not in {item["key"] for item in offered}:
        raise WorkflowRunError("run_read_only", "Only the current authored decision is available to you.", 403)
    # The offer is not authority: recheck current membership under the Run and membership locks.
    from .decider import require_node_decider

    await require_node_decider(db, run, user)
    return run


__all__ = ["require_run_action", "is_work_item_owner", "require_run", "require_start_scope",
           "require_workspace_view", "run_access"]
